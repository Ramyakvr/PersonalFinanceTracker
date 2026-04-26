"""Generic CSV import for assets and transactions.

Two scopes (assets, transactions) × two modes (append, update_by_name). Every run
records an `ImportJob` row for the audit trail.

CSV expectations (header row required):

Assets columns:
    name, category, subtype, currency, current_value,
    [cost_basis], [quantity], [notes], [exclude_from_allocation]

Transactions columns:
    date (YYYY-MM-DD), type (EXPENSE|INCOME), category, description,
    amount, currency, [notes], [is_recurring]

Unknown columns are ignored. Rows with missing required fields are skipped and
logged (file line number included). Mode "update_by_name" matches on the `name`
field for assets and on `description` + `date` + `type` for transactions; no
match -> inserted (so update_by_name is a superset of append).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction as db_tx

from core.models import (
    Asset,
    AssetCategory,
    Category,
    ImportJob,
    ImportStatus,
    Profile,
    Transaction,
    TxType,
)

MODE_APPEND = "append"
MODE_UPDATE = "update_by_name"
VALID_MODES = {MODE_APPEND, MODE_UPDATE}

ASSET_REQUIRED = {"name", "category", "subtype", "currency", "current_value"}
ASSET_OPTIONAL = {"cost_basis", "quantity", "notes", "exclude_from_allocation"}

TX_REQUIRED = {"date", "type", "category", "description", "amount", "currency"}
TX_OPTIONAL = {"notes", "is_recurring"}

BOOL_TRUE = {"1", "true", "yes", "y", "t"}


@dataclass
class ImportResult:
    job: ImportJob
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.job.status == ImportStatus.OK


def _to_decimal(raw: str) -> Decimal:
    return Decimal((raw or "").strip())


def _to_bool(raw: str) -> bool:
    return (raw or "").strip().lower() in BOOL_TRUE


def _iter_rows(file_obj) -> Iterable[dict]:
    """Accept a Django UploadedFile, bytes, str, or already-opened text file."""
    if hasattr(file_obj, "read"):
        data = file_obj.read()
        if isinstance(data, bytes):
            data = data.decode("utf-8-sig")
    elif isinstance(file_obj, bytes):
        data = file_obj.decode("utf-8-sig")
    else:
        data = str(file_obj)
    reader = csv.DictReader(io.StringIO(data))
    for row in reader:
        # Lower-case keys + strip whitespace around keys
        yield {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}


def _record_job(
    profile: Profile,
    *,
    scope: str,
    mode: str,
    source: str,
    filename: str,
    status: str,
    rows_imported: int,
    log: str,
) -> ImportJob:
    return ImportJob.objects.create(
        profile=profile,
        source=source,
        scope=scope,
        mode=mode,
        filename=filename,
        rows_imported=rows_imported,
        status=status,
        log=log,
    )


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def import_assets(
    profile: Profile,
    file_obj,
    *,
    mode: str = MODE_APPEND,
    source: str = "generic_csv",
    filename: str = "upload.csv",
) -> ImportResult:
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode: {mode}")

    categories = set(AssetCategory.values)
    result_job: ImportJob | None = None
    inserted = updated = skipped = 0
    errors: list[str] = []

    try:
        rows = list(_iter_rows(file_obj))
    except Exception as exc:  # pragma: no cover - csv lib is robust; defensive
        result_job = _record_job(
            profile,
            scope="assets",
            mode=mode,
            source=source,
            filename=filename,
            status=ImportStatus.ERROR,
            rows_imported=0,
            log=f"Could not parse CSV: {exc}",
        )
        return ImportResult(job=result_job, errors=[str(exc)])

    with db_tx.atomic():
        for line_no, row in enumerate(rows, start=2):  # header is line 1
            missing = [f for f in ASSET_REQUIRED if not row.get(f)]
            if missing:
                skipped += 1
                errors.append(f"line {line_no}: missing {', '.join(missing)}")
                continue

            cat = row["category"].upper()
            if cat not in categories:
                skipped += 1
                errors.append(f"line {line_no}: unknown category '{row['category']}'")
                continue

            try:
                current_value = _to_decimal(row["current_value"])
            except (InvalidOperation, ValueError):
                skipped += 1
                errors.append(f"line {line_no}: invalid current_value")
                continue

            fields = {
                "category": cat,
                "subtype": row["subtype"],
                "currency": row["currency"].upper()[:3],
                "current_value": current_value,
            }
            if row.get("cost_basis"):
                try:
                    fields["cost_basis"] = _to_decimal(row["cost_basis"])
                except (InvalidOperation, ValueError):
                    errors.append(f"line {line_no}: invalid cost_basis (ignored)")
            if row.get("quantity"):
                try:
                    fields["quantity"] = _to_decimal(row["quantity"])
                except (InvalidOperation, ValueError):
                    errors.append(f"line {line_no}: invalid quantity (ignored)")
            if row.get("notes"):
                fields["notes"] = row["notes"]
            if row.get("exclude_from_allocation"):
                fields["exclude_from_allocation"] = _to_bool(row["exclude_from_allocation"])

            if mode == MODE_UPDATE:
                existing = Asset.objects.filter(profile=profile, name=row["name"]).first()
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.save()
                    updated += 1
                    continue

            Asset.objects.create(profile=profile, name=row["name"], **fields)
            inserted += 1

    processed = inserted + updated
    status = ImportStatus.OK if processed > 0 or not rows else ImportStatus.ERROR
    log_lines = [f"inserted={inserted} updated={updated} skipped={skipped}"]
    if errors:
        log_lines.extend(errors[:50])
        if len(errors) > 50:
            log_lines.append(f"...and {len(errors) - 50} more")

    result_job = _record_job(
        profile,
        scope="assets",
        mode=mode,
        source=source,
        filename=filename,
        status=status,
        rows_imported=processed,
        log="\n".join(log_lines),
    )
    return ImportResult(
        job=result_job, inserted=inserted, updated=updated, skipped=skipped, errors=errors
    )


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------


def _parse_date(raw: str) -> date:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognized date: {raw}")


def _find_category(profile: Profile, name: str, tx_type: str) -> Category | None:
    qs = Category.objects.filter(type=tx_type, name__iexact=name).order_by(
        "profile__id"  # profile-scoped first, then system (NULL)
    )
    return qs.filter(profile=profile).first() or qs.filter(profile__isnull=True).first()


def import_transactions(
    profile: Profile,
    file_obj,
    *,
    mode: str = MODE_APPEND,
    source: str = "generic_csv",
    filename: str = "upload.csv",
) -> ImportResult:
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode: {mode}")

    inserted = updated = skipped = 0
    errors: list[str] = []
    try:
        rows = list(_iter_rows(file_obj))
    except Exception as exc:  # pragma: no cover
        job = _record_job(
            profile,
            scope="transactions",
            mode=mode,
            source=source,
            filename=filename,
            status=ImportStatus.ERROR,
            rows_imported=0,
            log=f"Could not parse CSV: {exc}",
        )
        return ImportResult(job=job, errors=[str(exc)])

    with db_tx.atomic():
        for line_no, row in enumerate(rows, start=2):
            missing = [f for f in TX_REQUIRED if not row.get(f)]
            if missing:
                skipped += 1
                errors.append(f"line {line_no}: missing {', '.join(missing)}")
                continue

            tx_type = row["type"].upper()
            if tx_type not in TxType.values:
                skipped += 1
                errors.append(f"line {line_no}: unknown type '{row['type']}'")
                continue

            try:
                tx_date = _parse_date(row["date"])
            except ValueError as exc:
                skipped += 1
                errors.append(f"line {line_no}: {exc}")
                continue

            try:
                amount = _to_decimal(row["amount"])
            except (InvalidOperation, ValueError):
                skipped += 1
                errors.append(f"line {line_no}: invalid amount")
                continue

            category = _find_category(profile, row["category"], tx_type)
            if category is None:
                skipped += 1
                errors.append(f"line {line_no}: unknown category '{row['category']}'")
                continue

            fields = {
                "type": tx_type,
                "date": tx_date,
                "category": category,
                "description": row["description"],
                "amount": amount,
                "currency": row["currency"].upper()[:3],
                "notes": row.get("notes", ""),
            }

            if mode == MODE_UPDATE:
                existing = Transaction.objects.filter(
                    profile=profile,
                    type=tx_type,
                    date=tx_date,
                    description__iexact=row["description"],
                ).first()
                if existing:
                    for k, v in fields.items():
                        setattr(existing, k, v)
                    existing.save()
                    updated += 1
                    continue

            Transaction.objects.create(profile=profile, **fields)
            inserted += 1

    processed = inserted + updated
    status = ImportStatus.OK if processed > 0 or not rows else ImportStatus.ERROR
    log_lines = [f"inserted={inserted} updated={updated} skipped={skipped}"]
    if errors:
        log_lines.extend(errors[:50])
        if len(errors) > 50:
            log_lines.append(f"...and {len(errors) - 50} more")

    job = _record_job(
        profile,
        scope="transactions",
        mode=mode,
        source=source,
        filename=filename,
        status=status,
        rows_imported=processed,
        log="\n".join(log_lines),
    )
    return ImportResult(job=job, inserted=inserted, updated=updated, skipped=skipped, errors=errors)


def list_import_jobs(profile: Profile, *, limit: int = 25):
    return ImportJob.objects.filter(profile=profile).order_by("-created_at")[:limit]
