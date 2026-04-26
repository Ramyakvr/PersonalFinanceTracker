from __future__ import annotations

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from core.auth import (
    InvalidPinFormatError,
    clear_pin,
    mark_unlocked,
    register_failed_attempt,
    session_locked_out,
    set_pin,
    verify_pin,
)
from core.forms import (
    AccountForm,
    AssetForm,
    BrokerImportForm,
    CategoryForm,
    EssentialsForm,
    GoalForm,
    ImportUploadForm,
    LiabilityForm,
    PasswordChangeForm,
    TransactionEditForm,
    TransactionFormSet,
)
from core.models import (
    Asset,
    AssetCategory,
    BrokerAccount,
    Category,
    CorporateAction,
    DividendRecord,
    Goal,
    Instrument,
    InstrumentKind,
    Liability,
    LiabilityCategory,
    Profile,
    StockTrade,
    Transaction,
    TxType,
)
from core.services import assets as asset_svc
from core.services import categories as category_svc
from core.services import goals as goal_svc
from core.services import liabilities as liability_svc
from core.services import snapshots as snapshot_svc
from core.services import transactions as tx_svc
from core.services.allocation import compute_allocation, monthly_sip_plan
from core.services.cashflow import cashflow
from core.services.essentials import compute_essentials, update_essentials
from core.services.insights import rule_based_insights
from core.services.networth import compute_net_worth, invested_amount
from core.services.periods import PERIOD_KEYS, PERIOD_LABELS, period_range
from core.services.tags import parse_tags
from core.subtypes import (
    all_categories,
    category_label,
    label_for,
    subtypes_for,
)
from core.utils import get_active_profile

# -----------------------------------------------------------------------------
# Hello / PIN views
# -----------------------------------------------------------------------------


def hello(request: HttpRequest) -> HttpResponse:
    """Dashboard. Empty-state-friendly: all widgets render with zero rows."""
    default_profile = Profile.objects.filter(is_default=True).select_related("user").first()
    if default_profile is None:
        # Pre-seed state: render the minimal "not configured" page.
        return render(
            request,
            "core/hello.html",
            {"db_ok": True, "profile": None, "base_currency": None},
        )

    nw = compute_net_worth(default_profile, top_n=5)
    alloc = compute_allocation(default_profile)
    from core.services.periods import period_range as _pr

    month_from, month_to = _pr("this_month")
    cf = cashflow(default_profile, date_from=month_from, date_to=month_to)
    insights = rule_based_insights(default_profile, net_worth=nw, allocation=alloc)
    invested = invested_amount(default_profile)

    # Month-over-month delta for the Net Worth KPI
    month_ago_snapshot = (
        snapshot_svc.list_snapshots(default_profile)
        .filter(taken_at__lte=_month_ago_datetime())
        .first()
    )
    nw_delta = nw.net_worth - month_ago_snapshot.net_worth if month_ago_snapshot else None

    # Investments: portfolio XIRR -- best effort; any FX / data issue surfaces
    # as ``None`` in the template rather than breaking the dashboard.
    from core.services.investments import portfolio_xirr as _portfolio_xirr

    try:
        portfolio_xirr_value = _portfolio_xirr(default_profile)
    except Exception:  # noqa: BLE001 — dashboard must never crash on investments
        portfolio_xirr_value = None
    portfolio_xirr_pct = (
        float(portfolio_xirr_value) * 100 if portfolio_xirr_value is not None else None
    )

    allocation_legend = _allocation_legend(alloc)
    context = {
        "db_ok": True,
        "profile": default_profile,
        "base_currency": nw.base_currency,
        "net_worth": nw,
        "allocation": alloc,
        "allocation_legend": allocation_legend,
        "allocation_json": _allocation_chart_json(alloc),
        "cashflow": cf,
        "insights": insights,
        "invested": invested,
        "nw_delta": nw_delta,
        "portfolio_xirr": portfolio_xirr_value,
        "portfolio_xirr_pct": portfolio_xirr_pct,
    }
    return render(request, "core/hello.html", context)


DONUT_COLORS = [
    "#15803d",
    "#2563eb",
    "#ca8a04",
    "#9333ea",
    "#db2777",
    "#0891b2",
    "#64748b",
    "#d97706",
]


def _allocation_legend(alloc) -> list[dict]:
    """Flat list of {label, color, pct} filtered to non-zero actuals, for donut legends."""
    out = []
    i = 0
    for row in alloc.rows:
        if row.actual_value <= 0:
            continue
        out.append(
            {
                "label": row.label,
                "color": DONUT_COLORS[i % len(DONUT_COLORS)],
                "pct": row.actual_pct,
            }
        )
        i += 1
    return out


def _target_legend(alloc) -> list[dict]:
    out = []
    i = 0
    for row in alloc.rows:
        if row.target_pct <= 0:
            continue
        out.append(
            {
                "label": row.label,
                "color": DONUT_COLORS[i % len(DONUT_COLORS)],
                "pct": row.target_pct,
            }
        )
        i += 1
    return out


def _month_ago_datetime():
    from datetime import timedelta

    from django.utils import timezone

    return timezone.now() - timedelta(days=30)


def _allocation_chart_json(alloc) -> str:
    import json

    labels = []
    values = []
    for row in alloc.rows:
        if row.actual_value > 0:
            labels.append(row.label)
            values.append(float(row.actual_value))
    return json.dumps({"labels": labels, "values": values})


@require_http_methods(["GET", "POST"])
def pin_set(request: HttpRequest) -> HttpResponse:
    user = request.user
    if request.method == "POST":
        action = request.POST.get("action", "set")
        if action == "clear":
            clear_pin(user)
            messages.success(request, "PIN cleared. App lock is off.")
            return redirect(reverse("pin_set"))

        pin = request.POST.get("pin", "")
        confirm = request.POST.get("confirm", "")
        if pin != confirm:
            messages.error(request, "PINs do not match.")
        else:
            try:
                set_pin(user, pin)
            except InvalidPinFormatError as exc:
                messages.error(request, str(exc))
            else:
                mark_unlocked(request.session)
                messages.success(request, "PIN set. App lock is on.")
                return redirect(reverse("pin_set"))

    return render(request, "auth/pin_set.html", {"has_pin": bool(user.app_lock_hash)})


@require_http_methods(["GET", "POST"])
def pin_unlock(request: HttpRequest) -> HttpResponse:
    user = request.user
    next_path = request.GET.get("next") or request.POST.get("next") or reverse("hello")

    if not user.is_authenticated or not user.app_lock_hash:
        return redirect(next_path)

    locked, remaining = session_locked_out(request.session)
    if request.method == "POST" and not locked:
        pin = request.POST.get("pin", "")
        if verify_pin(user, pin):
            mark_unlocked(request.session)
            return redirect(next_path)
        register_failed_attempt(request.session)
        locked, remaining = session_locked_out(request.session)
        if not locked:
            messages.error(request, "Incorrect PIN.")

    context = {"next_path": next_path, "locked": locked, "remaining": remaining}
    return render(request, "auth/pin_unlock.html", context)


# -----------------------------------------------------------------------------
# Wealth: Assets
# -----------------------------------------------------------------------------


def _require_profile(request: HttpRequest) -> Profile:
    profile = get_active_profile(request)
    if profile is None:
        raise Http404("No default profile. Run `manage.py seed`.")
    return profile


def asset_list(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    currency = request.GET.get("currency", "").strip()

    rows = asset_svc.list_assets(profile, search=search, category=category, currency=currency)

    total_by_ccy: dict[str, int] = {}
    for a in rows:
        total_by_ccy[a.currency] = total_by_ccy.get(a.currency, 0) + 1  # count per ccy tag
    currencies_in_use = asset_svc.distinct_currencies(profile)

    context = {
        "active_tab": "assets",
        "assets": rows,
        "search": search,
        "selected_category": category,
        "selected_currency": currency,
        "categories": AssetCategory.choices,
        "currencies": currencies_in_use,
        "count": len(rows) if isinstance(rows, list) else rows.count(),
    }
    return render(request, "wealth/assets_list.html", context)


@require_http_methods(["GET", "POST"])
def asset_new(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    category = request.GET.get("category", "").strip()
    subtype = request.GET.get("subtype", "").strip()

    # Step 1: no category chosen yet -> show grid.
    if not category and request.method == "GET":
        return render(
            request,
            "wealth/asset_wizard.html",
            {
                "active_tab": "assets",
                "step": 1,
                "categories": all_categories(),
                "kind": "asset",
            },
        )

    # Step 2: show the form for the chosen category (and optional preselected subtype).
    subtype_choices = subtypes_for(category)
    if not subtype_choices:
        messages.error(request, "Unknown category.")
        return redirect(reverse("asset_new"))

    # Default subtype if not explicitly chosen.
    initial_subtype = subtype or subtype_choices[0][0]

    if request.method == "POST":
        form = AssetForm(request.POST)
        if form.is_valid():
            tag_objs = parse_tags(profile, form.cleaned_data.get("tags_raw", ""))
            fields = {k: v for k, v in form.cleaned_data.items() if k != "tags_raw"}
            asset = asset_svc.create_asset(profile, tags=tag_objs, **fields)
            messages.success(request, f"Saved {asset.name}.")
            if request.POST.get("action") == "save_and_add":
                return redirect(
                    f"{reverse('asset_new')}?category={category}&subtype={initial_subtype}"
                )
            return redirect(reverse("asset_list"))
    else:
        form = AssetForm(
            initial={"category": category, "subtype": initial_subtype, "currency": "INR"}
        )

    return render(
        request,
        "wealth/asset_form.html",
        {
            "active_tab": "assets",
            "step": 2,
            "kind": "asset",
            "form": form,
            "category": category,
            "category_label": category_label(category),
            "subtype_choices": subtype_choices,
            "initial_subtype_label": label_for(initial_subtype),
            "is_edit": False,
        },
    )


@require_http_methods(["GET", "POST"])
def asset_edit(request: HttpRequest, asset_id: int) -> HttpResponse:
    profile = _require_profile(request)
    asset = get_object_or_404(Asset, id=asset_id, profile=profile)

    if request.method == "POST":
        form = AssetForm(request.POST, instance=asset)
        if form.is_valid():
            tag_objs = parse_tags(profile, form.cleaned_data.get("tags_raw", ""))
            fields = {k: v for k, v in form.cleaned_data.items() if k != "tags_raw"}
            asset_svc.update_asset(asset, tags=tag_objs, **fields)
            messages.success(request, "Saved changes.")
            return redirect(reverse("asset_list"))
    else:
        form = AssetForm(instance=asset)

    category = asset.category
    subtype_choices = subtypes_for(category)
    return render(
        request,
        "wealth/asset_form.html",
        {
            "active_tab": "assets",
            "step": 2,
            "kind": "asset",
            "form": form,
            "category": category,
            "category_label": category_label(category),
            "subtype_choices": subtype_choices,
            "initial_subtype_label": label_for(asset.subtype),
            "is_edit": True,
            "instance": asset,
        },
    )


@require_POST
def asset_delete(request: HttpRequest, asset_id: int) -> HttpResponse:
    profile = _require_profile(request)
    asset = get_object_or_404(Asset, id=asset_id, profile=profile)
    asset_svc.delete_asset(asset)
    messages.success(request, "Asset deleted.")
    return redirect(reverse("asset_list"))


# -----------------------------------------------------------------------------
# Wealth: Liabilities
# -----------------------------------------------------------------------------


def liability_list(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    search = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").strip()
    currency = request.GET.get("currency", "").strip()

    rows = liability_svc.list_liabilities(
        profile, search=search, category=category, currency=currency
    )

    context = {
        "active_tab": "liabilities",
        "liabilities": rows,
        "search": search,
        "selected_category": category,
        "selected_currency": currency,
        "categories": LiabilityCategory.choices,
        "currencies": liability_svc.distinct_currencies(profile),
        "count": rows.count() if hasattr(rows, "count") else len(rows),
    }
    return render(request, "wealth/liabilities_list.html", context)


@require_http_methods(["GET", "POST"])
def liability_new(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    category = request.GET.get("category", "").strip()

    if not category and request.method == "GET":
        return render(
            request,
            "wealth/liability_wizard.html",
            {
                "active_tab": "liabilities",
                "step": 1,
                "categories": LiabilityCategory.choices,
                "kind": "liability",
            },
        )

    if category not in dict(LiabilityCategory.choices):
        messages.error(request, "Unknown category.")
        return redirect(reverse("liability_new"))

    if request.method == "POST":
        form = LiabilityForm(request.POST)
        if form.is_valid():
            tag_objs = parse_tags(profile, form.cleaned_data.get("tags_raw", ""))
            fields = {k: v for k, v in form.cleaned_data.items() if k != "tags_raw"}
            liability = liability_svc.create_liability(profile, tags=tag_objs, **fields)
            messages.success(request, f"Saved {liability.name}.")
            if request.POST.get("action") == "save_and_add":
                return redirect(f"{reverse('liability_new')}?category={category}")
            return redirect(reverse("liability_list"))
    else:
        form = LiabilityForm(initial={"category": category, "currency": "INR"})

    return render(
        request,
        "wealth/liability_form.html",
        {
            "active_tab": "liabilities",
            "step": 2,
            "kind": "liability",
            "form": form,
            "category": category,
            "category_label": dict(LiabilityCategory.choices)[category],
            "is_edit": False,
        },
    )


@require_http_methods(["GET", "POST"])
def liability_edit(request: HttpRequest, liability_id: int) -> HttpResponse:
    profile = _require_profile(request)
    liability = get_object_or_404(Liability, id=liability_id, profile=profile)

    if request.method == "POST":
        form = LiabilityForm(request.POST, instance=liability)
        if form.is_valid():
            tag_objs = parse_tags(profile, form.cleaned_data.get("tags_raw", ""))
            fields = {k: v for k, v in form.cleaned_data.items() if k != "tags_raw"}
            liability_svc.update_liability(liability, tags=tag_objs, **fields)
            messages.success(request, "Saved changes.")
            return redirect(reverse("liability_list"))
    else:
        form = LiabilityForm(instance=liability)

    return render(
        request,
        "wealth/liability_form.html",
        {
            "active_tab": "liabilities",
            "step": 2,
            "kind": "liability",
            "form": form,
            "category": liability.category,
            "category_label": dict(LiabilityCategory.choices).get(
                liability.category, liability.category
            ),
            "is_edit": True,
            "instance": liability,
        },
    )


@require_POST
def liability_delete(request: HttpRequest, liability_id: int) -> HttpResponse:
    profile = _require_profile(request)
    liability = get_object_or_404(Liability, id=liability_id, profile=profile)
    liability_svc.delete_liability(liability)
    messages.success(request, "Liability deleted.")
    return redirect(reverse("liability_list"))


# -----------------------------------------------------------------------------
# Wealth: Allocation + Snapshots
# -----------------------------------------------------------------------------


def allocation_view(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    alloc = compute_allocation(profile)
    sip_plan = monthly_sip_plan(alloc)

    actual_json = _allocation_chart_json(alloc)
    target_json = _target_chart_json(alloc)

    return render(
        request,
        "wealth/allocation.html",
        {
            "active_tab": "allocation",
            "allocation": alloc,
            "sip_plan": sip_plan,
            "actual_json": actual_json,
            "target_json": target_json,
            "actual_legend": _allocation_legend(alloc),
            "target_legend": _target_legend(alloc),
            "base_currency": profile.user.base_currency,
        },
    )


def _target_chart_json(alloc) -> str:
    import json

    labels = []
    values = []
    for row in alloc.rows:
        if row.target_pct > 0:
            labels.append(row.label)
            values.append(float(row.target_pct))
    return json.dumps({"labels": labels, "values": values})


def snapshots_view(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    window = request.GET.get("window", "6m")
    if window not in {"1m", "6m", "1y", "all"}:
        window = "6m"
    series = snapshot_svc.snapshot_series(profile, window=window)
    snaps = snapshot_svc.list_snapshots(profile)

    import json

    return render(
        request,
        "wealth/snapshots.html",
        {
            "active_tab": "snapshots",
            "snapshots": snaps,
            "series_json": json.dumps(series),
            "count": snaps.count(),
            "window": window,
            "base_currency": profile.user.base_currency,
        },
    )


@require_POST
def snapshot_create(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    from core.models import SnapshotSource

    snapshot_svc.take_snapshot(profile, source=SnapshotSource.MANUAL)
    messages.success(request, "Snapshot taken.")
    return redirect(reverse("snapshots"))


# -----------------------------------------------------------------------------
# Money: Transactions
# -----------------------------------------------------------------------------


from datetime import date as date_type  # noqa: E402


def _parse_period(request: HttpRequest):
    period = request.GET.get("period", "30d")
    if period not in PERIOD_KEYS:
        period = "30d"

    if period == "custom":
        from datetime import datetime

        try:
            d_from = datetime.strptime(request.GET.get("from", ""), "%Y-%m-%d").date()
        except ValueError:
            d_from = None
        try:
            d_to = datetime.strptime(request.GET.get("to", ""), "%Y-%m-%d").date()
        except ValueError:
            d_to = None
    else:
        d_from, d_to = period_range(period)

    return period, d_from, d_to


def _tx_type_from_segment(segment: str) -> str:
    return TxType.INCOME if segment == "income" else TxType.EXPENSE


def transaction_list(request: HttpRequest, segment: str) -> HttpResponse:
    profile = _require_profile(request)
    tx_type = _tx_type_from_segment(segment)

    period, d_from, d_to = _parse_period(request)
    search = request.GET.get("q", "").strip()
    category_id = request.GET.get("category") or None
    try:
        category_id_int = int(category_id) if category_id else None
    except ValueError:
        category_id_int = None

    rows = tx_svc.list_transactions(
        profile,
        tx_type=tx_type,
        date_from=d_from,
        date_to=d_to,
        search=search,
        category_id=category_id_int,
    )
    base_currency = profile.user.base_currency
    total = tx_svc.total_non_exempt(rows, currency=base_currency)
    categories = category_svc.list_categories(profile, tx_type)

    period_chips = [{"key": k, "label": PERIOD_LABELS[k]} for k in PERIOD_KEYS if k != "custom"]

    context = {
        "segment": segment,
        "tx_type": tx_type,
        "active_tab": segment,
        "transactions": rows,
        "period": period,
        "period_chips": period_chips,
        "date_from": d_from,
        "date_to": d_to,
        "search": search,
        "selected_category": category_id_int,
        "categories": categories,
        "total": total,
        "total_currency": base_currency,
        "count": rows.count() if hasattr(rows, "count") else len(rows),
    }
    return render(request, "money/transaction_list.html", context)


@require_http_methods(["GET", "POST"])
def transaction_new(request: HttpRequest, segment: str) -> HttpResponse:
    profile = _require_profile(request)
    tx_type = _tx_type_from_segment(segment)
    categories = tx_svc.category_choices(profile, tx_type)

    if not categories:
        messages.error(request, "No categories available. Seed the database first.")
        return redirect(reverse("transaction_list", args=[segment]))

    formset_kwargs = {"form_kwargs": {"categories": categories}}

    if request.method == "POST":
        formset = TransactionFormSet(request.POST, **formset_kwargs)
        if formset.is_valid():
            created = 0
            for form in formset:
                data = form.cleaned_data
                if not data:
                    continue
                cat = get_object_or_404(
                    Category,
                    id=data["category"],
                    type=tx_type,
                )
                tag_objs = parse_tags(profile, data.get("tags_raw", ""))
                tx_svc.create_transaction(
                    profile,
                    tags=tag_objs,
                    is_recurring=data.get("is_recurring", False),
                    type=tx_type,
                    date=data["date"],
                    category=cat,
                    description=data["description"],
                    amount=data["amount"],
                    currency=data["currency"],
                    notes=data.get("notes", ""),
                )
                created += 1
            if created:
                messages.success(
                    request, f"Saved {created} {segment} row{'s' if created != 1 else ''}."
                )
                return redirect(reverse("transaction_list", args=[segment]))
            messages.error(request, "Nothing to save \u2014 add at least one row.")
    else:
        formset = TransactionFormSet(
            initial=[{"date": date_type.today(), "currency": "INR"}], **formset_kwargs
        )

    return render(
        request,
        "money/transaction_form.html",
        {
            "active_tab": segment,
            "segment": segment,
            "tx_type": tx_type,
            "formset": formset,
            "categories": categories,
        },
    )


@require_http_methods(["GET", "POST"])
def transaction_edit(request: HttpRequest, tx_id: int) -> HttpResponse:
    profile = _require_profile(request)
    tx = get_object_or_404(Transaction, id=tx_id, profile=profile)
    segment = "income" if tx.type == TxType.INCOME else "expenses"
    categories = tx_svc.category_choices(profile, tx.type)

    if request.method == "POST":
        form = TransactionEditForm(request.POST, instance=tx, categories=categories)
        if form.is_valid():
            tag_objs = parse_tags(profile, form.cleaned_data.get("tags_raw", ""))
            is_recurring = form.cleaned_data.get("is_recurring", False)
            fields = {
                k: v for k, v in form.cleaned_data.items() if k not in {"tags_raw", "is_recurring"}
            }
            tx_svc.update_transaction(tx, tags=tag_objs, is_recurring=is_recurring, **fields)
            messages.success(request, "Saved.")
            return redirect(reverse("transaction_list", args=[segment]))
    else:
        form = TransactionEditForm(instance=tx, categories=categories)

    return render(
        request,
        "money/transaction_edit.html",
        {
            "active_tab": segment,
            "segment": segment,
            "form": form,
            "transaction": tx,
        },
    )


@require_POST
def transaction_delete(request: HttpRequest, tx_id: int) -> HttpResponse:
    profile = _require_profile(request)
    tx = get_object_or_404(Transaction, id=tx_id, profile=profile)
    segment = "income" if tx.type == TxType.INCOME else "expenses"
    tx_svc.delete_transaction(tx)
    messages.success(request, "Transaction deleted.")
    return redirect(reverse("transaction_list", args=[segment]))


def insights_placeholder(request: HttpRequest) -> HttpResponse:
    _require_profile(request)
    return render(request, "money/insights_placeholder.html", {"active_tab": "insights"})


# -----------------------------------------------------------------------------
# Settings: Preferences
# -----------------------------------------------------------------------------


def settings_redirect(request: HttpRequest) -> HttpResponse:
    return redirect(reverse("preferences"))


@require_http_methods(["GET", "POST"])
def preferences(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    user = request.user

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "set_base_currency":
            ccy = request.POST.get("base_currency", "").strip()
            if ccy:
                user.base_currency = ccy[:3].upper()
                user.save(update_fields=["base_currency"])
                messages.success(request, f"Base currency set to {user.base_currency}.")
        return redirect(reverse("preferences"))

    categorized = category_svc.list_all_categories(profile)
    context = {
        "active_settings": "preferences",
        "base_currency": user.base_currency,
        "currency_choices": ["INR", "USD", "EUR", "GBP", "SGD", "AED"],
        "expense_categories": categorized["expense"],
        "income_categories": categorized["income"],
        "add_form": CategoryForm(),
    }
    return render(request, "settings/preferences.html", context)


@require_POST
def category_toggle_exempt(request: HttpRequest, cat_id: int) -> HttpResponse:
    profile = _require_profile(request)
    category = get_object_or_404(Category.objects.filter(profile__in=[profile, None]), id=cat_id)
    # System-default categories (profile=None) aren't editable from another user's session; we still
    # allow the toggle since there's only one user on a local machine.
    category_svc.set_exempt(category, is_exempt=not category.is_exempt)
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "settings/_category_row.html", {"category": category, "profile": profile}
        )
    return redirect(reverse("preferences"))


@require_POST
def category_create(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    form = CategoryForm(request.POST)
    if form.is_valid():
        try:
            category_svc.create_custom(
                profile,
                tx_type=form.cleaned_data["type"],
                name=form.cleaned_data["name"],
                is_exempt=form.cleaned_data.get("is_exempt", False),
            )
            messages.success(request, "Category added.")
        except ValueError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Could not add category.")
    return redirect(reverse("preferences"))


@require_POST
def category_delete(request: HttpRequest, cat_id: int) -> HttpResponse:
    profile = _require_profile(request)
    category = get_object_or_404(Category, id=cat_id, profile=profile)
    try:
        category_svc.delete_custom(category)
        messages.success(request, "Category removed.")
    except ValueError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("preferences"))


# -----------------------------------------------------------------------------
# Essentials + Goals
# -----------------------------------------------------------------------------


def _get_or_create_essentials(profile):
    from core.models import EssentialsState

    state, _ = EssentialsState.objects.get_or_create(profile=profile)
    return state


def essentials_view(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    report = compute_essentials(profile)
    form = EssentialsForm(instance=_get_or_create_essentials(profile))
    return render(
        request,
        "essentials/essentials.html",
        {
            "active_tab": "essentials",
            "report": report,
            "form": form,
            "base_currency": profile.user.base_currency,
        },
    )


@require_POST
def essentials_update(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    form = EssentialsForm(request.POST, instance=_get_or_create_essentials(profile))
    if form.is_valid():
        update_essentials(profile, **form.cleaned_data)
        messages.success(request, "Essentials updated.")
    else:
        messages.error(request, "Could not save. Check the inputs.")
    return redirect(reverse("essentials"))


def goal_list(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    goals = goal_svc.list_goals(profile)
    progress_rows = [goal_svc.progress(profile, g) for g in goals]
    return render(
        request,
        "essentials/goals_list.html",
        {
            "active_tab": "goals",
            "progress_rows": progress_rows,
            "count": len(progress_rows),
            "base_currency": profile.user.base_currency,
        },
    )


@require_http_methods(["GET", "POST"])
def goal_new(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    if request.method == "POST":
        form = GoalForm(
            request.POST,
            template_choices=goal_svc.GOAL_TEMPLATES,
            track_choices=goal_svc.TRACK_CHOICES,
        )
        if form.is_valid():
            data = form.cleaned_data
            asset_ids = data.pop("linked_asset_ids_raw", []) or []
            goal_svc.create_goal(profile, linked_asset_ids=asset_ids, **data)
            messages.success(request, "Goal created.")
            return redirect(reverse("goal_list"))
    else:
        form = GoalForm(
            template_choices=goal_svc.GOAL_TEMPLATES, track_choices=goal_svc.TRACK_CHOICES
        )
    return render(
        request,
        "essentials/goal_form.html",
        {
            "active_tab": "goals",
            "form": form,
            "is_edit": False,
        },
    )


@require_http_methods(["GET", "POST"])
def goal_edit(request: HttpRequest, goal_id: int) -> HttpResponse:
    profile = _require_profile(request)
    goal = get_object_or_404(Goal, id=goal_id, profile=profile)
    if request.method == "POST":
        form = GoalForm(
            request.POST,
            instance=goal,
            template_choices=goal_svc.GOAL_TEMPLATES,
            track_choices=goal_svc.TRACK_CHOICES,
        )
        if form.is_valid():
            data = form.cleaned_data
            asset_ids = data.pop("linked_asset_ids_raw", []) or []
            goal_svc.update_goal(goal, linked_asset_ids=asset_ids, **data)
            messages.success(request, "Goal updated.")
            return redirect(reverse("goal_list"))
    else:
        form = GoalForm(
            instance=goal,
            template_choices=goal_svc.GOAL_TEMPLATES,
            track_choices=goal_svc.TRACK_CHOICES,
        )
    return render(
        request,
        "essentials/goal_form.html",
        {
            "active_tab": "goals",
            "form": form,
            "is_edit": True,
            "goal": goal,
        },
    )


@require_POST
def goal_delete(request: HttpRequest, goal_id: int) -> HttpResponse:
    profile = _require_profile(request)
    goal = get_object_or_404(Goal, id=goal_id, profile=profile)
    goal_svc.delete_goal(goal)
    messages.success(request, "Goal deleted.")
    return redirect(reverse("goal_list"))


def inflation_calculator(request: HttpRequest) -> HttpResponse:
    """Tiny helper: GET returns the form; POST-ish via GET params returns result."""
    from decimal import InvalidOperation

    amount = request.GET.get("amount", "")
    years = request.GET.get("years", "")
    inflation_pct = request.GET.get("inflation", "6")
    result = None
    try:
        if amount and years:
            result = goal_svc.inflate(
                __import__("decimal").Decimal(amount),
                int(years),
                __import__("decimal").Decimal(inflation_pct) / __import__("decimal").Decimal("100"),
            )
    except (ValueError, InvalidOperation):
        result = None
    return render(
        request,
        "essentials/inflation_calculator.html",
        {
            "active_tab": "goals",
            "amount": amount,
            "years": years,
            "inflation_pct": inflation_pct,
            "result": result,
        },
    )


# -----------------------------------------------------------------------------
# Phase 6: Import / Export / Settings tabs
# -----------------------------------------------------------------------------


def _import_context(profile, scope, mode):
    from core.services import imports as imp_svc

    return {
        "active_tab": "import",
        "scope": scope,
        "mode": mode,
        "jobs": imp_svc.list_import_jobs(profile),
    }


@require_http_methods(["GET", "POST"])
def import_view(request: HttpRequest) -> HttpResponse:
    from core.services import imports as imp_svc

    profile = _require_profile(request)
    scope = request.GET.get("scope") or request.POST.get("scope", "assets")
    if scope not in {"assets", "transactions", "broker"}:
        scope = "assets"
    mode = request.POST.get("mode") or request.GET.get("mode") or imp_svc.MODE_APPEND
    if mode not in imp_svc.VALID_MODES:
        mode = imp_svc.MODE_APPEND

    if scope == "broker":
        form = ImportUploadForm()
        if request.method == "POST":
            broker_form = BrokerImportForm(request.POST, request.FILES)
            if broker_form.is_valid():
                broker_key = broker_form.cleaned_data["broker"]
                tradebook_files = broker_form.cleaned_data.get("tradebook") or []
                dividend_files = broker_form.cleaned_data.get("dividends") or []

                from core.services.imports.brokers import (
                    get_adapter as _get_adapter,
                )
                from core.services.imports.brokers import (
                    known_client_ids_for as _known_for,
                )

                adapter = _get_adapter(broker_key)
                expected_ids = set(_known_for(broker_key))

                def _resolve_label(upload) -> tuple[str, str | None]:
                    """Sniff the broker-issued client ID from the upload.

                    Returns ``(label, warning)``. ``label`` is empty when
                    extraction fails or the extracted ID is not in the
                    expected list -- the caller skips that file. Reads the
                    file once; the upload's stream is rewound so the
                    importer can re-read from byte 0.
                    """
                    raw = upload.read()
                    upload.seek(0)
                    try:
                        detected = adapter.parse_client_id(raw) or ""
                    except Exception:  # noqa: BLE001 -- detection is best-effort
                        detected = ""
                    if not detected:
                        return "", (
                            f"{getattr(upload, 'name', 'file')}: client ID could "
                            f"not be extracted. Expected one of "
                            f"{sorted(expected_ids) or 'none'}."
                        )
                    if expected_ids and detected not in expected_ids:
                        return "", (
                            f"{getattr(upload, 'name', 'file')}: client ID "
                            f"{detected!r} is not in the known list for "
                            f"{broker_key} ({sorted(expected_ids) or 'none'})."
                        )
                    return detected, None

                total_inserted = 0
                total_skipped = 0
                errors_bucket: list[str] = []

                if broker_key == "chola":
                    # Chola ships a single mixed PDF -> every uploaded file
                    # (whether dropped in the tradebook or dividends slot) is
                    # routed through import_statement.
                    for upload in [*tradebook_files, *dividend_files]:
                        filename = getattr(upload, "name", "statement")
                        label, warning = _resolve_label(upload)
                        if warning:
                            errors_bucket.append(warning)
                        if not label:
                            continue
                        result = imp_svc.import_statement(
                            profile,
                            broker_key=broker_key,
                            account_label=label,
                            file=upload,
                            filename=filename,
                        )
                        total_inserted += result.inserted
                        total_skipped += result.skipped
                        errors_bucket.extend(result.errors)
                else:
                    # Zerodha / Aionion -> two distinct XLSX file types.
                    for upload in tradebook_files:
                        fn = getattr(upload, "name", "tradebook.xlsx")
                        label, warning = _resolve_label(upload)
                        if warning:
                            errors_bucket.append(warning)
                        if not label:
                            continue
                        r = imp_svc.import_tradebook(
                            profile,
                            broker_key=broker_key,
                            account_label=label,
                            file=upload,
                            filename=fn,
                        )
                        total_inserted += r.inserted
                        total_skipped += r.skipped
                        errors_bucket.extend(r.errors)
                    for upload in dividend_files:
                        fn = getattr(upload, "name", "dividends.xlsx")
                        label, warning = _resolve_label(upload)
                        if warning:
                            errors_bucket.append(warning)
                        if not label:
                            continue
                        r = imp_svc.import_dividends(
                            profile,
                            broker_key=broker_key,
                            account_label=label,
                            file=upload,
                            filename=fn,
                        )
                        total_inserted += r.inserted
                        total_skipped += r.skipped
                        errors_bucket.extend(r.errors)

                if total_inserted or total_skipped:
                    messages.success(
                        request,
                        (
                            f"Broker import done: +{total_inserted} new, "
                            f"−{total_skipped} duplicate/skipped."
                        ),
                    )
                else:
                    messages.warning(
                        request,
                        "Broker import finished with nothing persisted. Check the job log below.",
                    )
                for err in errors_bucket[:3]:
                    messages.warning(request, err)
                return redirect(f"{reverse('import_view')}?scope=broker")
            messages.error(request, "Upload at least one broker-native file.")
        else:
            broker_form = BrokerImportForm()
    else:
        broker_form = BrokerImportForm()
        if request.method == "POST":
            form = ImportUploadForm(request.POST, request.FILES)
            if form.is_valid():
                upload = form.cleaned_data["file"]
                fn = getattr(upload, "name", "upload.csv")
                if scope == "assets":
                    result = imp_svc.import_assets(profile, upload, mode=mode, filename=fn)
                else:
                    result = imp_svc.import_transactions(profile, upload, mode=mode, filename=fn)
                if result.ok:
                    messages.success(
                        request,
                        (
                            f"Imported {result.inserted + result.updated} rows "
                            f"(+{result.inserted} new, ~{result.updated} updated, "
                            f"−{result.skipped} skipped)."
                        ),
                    )
                else:
                    messages.error(
                        request,
                        "Import failed — no rows processed. See job log below.",
                    )
                return redirect(f"{reverse('import_view')}?scope={scope}")
            messages.error(request, "Choose a CSV file to upload.")
        else:
            form = ImportUploadForm()

    ctx = _import_context(profile, scope, mode)
    ctx["form"] = form
    ctx["broker_form"] = broker_form
    return render(request, "tools/import.html", ctx)


# ---- Settings: Account -----------------------------------------------------


@require_http_methods(["GET", "POST"])
def settings_account(request: HttpRequest) -> HttpResponse:
    _require_profile(request)
    user = request.user
    profile_form = AccountForm(instance=user)
    password_form = PasswordChangeForm()

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "save_profile":
            profile_form = AccountForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile saved.")
                return redirect(reverse("settings_account"))
        elif action == "change_password":
            password_form = PasswordChangeForm(request.POST)
            if password_form.is_valid():
                user.set_password(password_form.cleaned_data["new_password"])
                user.save(update_fields=["password"])
                messages.success(request, "Password updated.")
                return redirect(reverse("settings_account"))

    return render(
        request,
        "settings/account.html",
        {
            "active_settings": "account",
            "profile_form": profile_form,
            "password_form": password_form,
            "has_pin": bool(user.app_lock_hash),
        },
    )


# ---- Settings: Data (export / import / wipe) -------------------------------


@require_http_methods(["GET", "POST"])
def settings_data(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    from core.models import UserPreferences as _UP
    from core.services import exports as exp_svc

    prefs, _ = _UP.objects.get_or_create(user=profile.user)

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "toggle_live_prices":
            prefs.live_price_enabled = bool(request.POST.get("live_price_enabled"))
            prefs.save(update_fields=["live_price_enabled"])
            if prefs.live_price_enabled:
                messages.success(
                    request,
                    "Live prices enabled. Nightly refresh + manual 'Refresh' now wired up.",
                )
            else:
                messages.info(request, "Live price fetching turned off.")
            return redirect(reverse("settings_data"))

    return render(
        request,
        "settings/data.html",
        {
            "active_settings": "data",
            "csv_tables": exp_svc.CSV_TABLES,
            "prefs": prefs,
        },
    )


def settings_export_json(request: HttpRequest) -> HttpResponse:
    import json

    profile = _require_profile(request)
    from core.services import exports as exp_svc

    data = exp_svc.export_all(profile)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    filename = f"finance-export-{_today_stamp()}.json"
    resp = HttpResponse(payload, content_type="application/json")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def settings_export_csv(request: HttpRequest, table: str) -> HttpResponse:
    profile = _require_profile(request)
    from core.services import exports as exp_svc

    try:
        payload = exp_svc.export_csv(profile, table)
    except ValueError as exc:
        raise Http404("Unknown table") from exc
    filename = f"{table}-{_today_stamp()}.csv"
    resp = HttpResponse(payload, content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@require_POST
def settings_wipe(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    if request.POST.get("confirm") != "WIPE":
        messages.error(request, "Type WIPE to confirm.")
        return redirect(reverse("settings_data"))
    from core.services import exports as exp_svc

    counts = exp_svc.wipe_data(profile)
    total = sum(counts.values())
    messages.success(request, f"Wiped {total} rows across {len(counts)} tables.")
    return redirect(reverse("settings_data"))


def _today_stamp() -> str:
    from datetime import datetime as _dt

    return _dt.now().strftime("%Y%m%d")


# ---- Settings: Recurring + Billing (minimal read-only pages) --------------


def settings_recurring(request: HttpRequest) -> HttpResponse:
    profile = _require_profile(request)
    from core.models import RecurringRule

    rules = RecurringRule.objects.filter(profile=profile).order_by("start_date")
    return render(
        request,
        "settings/recurring.html",
        {
            "active_settings": "recurring",
            "rules": rules,
        },
    )


def settings_billing(request: HttpRequest) -> HttpResponse:
    _require_profile(request)
    return render(
        request,
        "settings/billing.html",
        {"active_settings": "billing"},
    )


# =============================================================================
# Phase D: Investments page
# =============================================================================


def _make_price_lookup(profile: Profile):
    """Return a closure compatible with ``investments`` service price_lookup."""

    from core.services.prices import latest_price as _latest_price

    def _lookup(instrument, when):
        return _latest_price(instrument, when)

    return _lookup


def investments_list(request: HttpRequest) -> HttpResponse:
    """List every Instrument with trades/dividends for the default profile."""

    profile = Profile.objects.filter(is_default=True).select_related("user").first()
    if profile is None:
        return render(
            request,
            "wealth/investments/list.html",
            {"active": "investments", "profile": None},
        )

    from core.services.investments import instrument_breakdown, portfolio_summary

    # --- Filter parsing -----------------------------------------------------
    # The broker filter is keyed on BrokerAccount.id so users with multiple
    # accounts at one broker (e.g. two Zerodha demats) can
    # drill into one client ID at a time.
    raw_broker = (request.GET.get("broker") or "").strip()
    selected_broker_account_id: int | None = int(raw_broker) if raw_broker.isdigit() else None
    # Default to Equity when the param is absent; an explicit empty string
    # (chosen via the "All segments" option) keeps the filter off.
    if "kind" in request.GET:
        selected_kind = request.GET.get("kind", "").strip().upper()
    else:
        selected_kind = "STOCK"
    sort = (request.GET.get("sort") or "name").strip()
    sort_dir = (request.GET.get("dir") or "asc").strip()
    include_old = request.GET.get("include_old") in {"1", "true", "on", "yes"}

    all_broker_accounts = list(
        BrokerAccount.objects.filter(profile=profile).order_by("broker_key", "account_label")
    )
    ba_filter = None
    if selected_broker_account_id is not None:
        ba_filter = next(
            (ba for ba in all_broker_accounts if ba.id == selected_broker_account_id),
            None,
        )

    price_lookup = _make_price_lookup(profile)
    summary = portfolio_summary(
        profile,
        broker_account=ba_filter,
        kind=selected_kind or None,
        price_lookup=price_lookup,
    )

    # --- Find instruments with activity in scope ----------------------------
    trade_q = StockTrade.objects.filter(profile=profile)
    div_q = DividendRecord.objects.filter(profile=profile)
    if ba_filter:
        trade_q = trade_q.filter(broker_account=ba_filter)
        div_q = div_q.filter(broker_account=ba_filter)
    if selected_kind:
        trade_q = trade_q.filter(instrument__kind=selected_kind)
        div_q = div_q.filter(instrument__kind=selected_kind)

    active_ids = set(trade_q.values_list("instrument_id", flat=True))
    active_ids.update(div_q.values_list("instrument_id", flat=True))

    rows = []
    stale_count = 0
    for instr in Instrument.objects.filter(id__in=active_ids).order_by("name"):
        br = instrument_breakdown(
            profile, instr, broker_account=ba_filter, price_lookup=price_lookup
        )
        # Pre-compute presentation-friendly values so the template stays simple.
        xirr_pct = float(br.xirr) * 100 if br.xirr is not None else None
        price, is_stale = price_lookup(instr, None)
        is_old = (br.qty_held or 0) <= 0
        if is_old and not include_old:
            continue
        # Weight % is filled in below once we know the displayed total CV.
        if br.current_value is not None and summary.total_current_value:
            br.weight_pct = br.current_value / summary.total_current_value
        weight_pct = float(br.weight_pct) * 100 if br.weight_pct is not None else None
        if price is not None and is_stale:
            stale_count += 1
        rows.append(
            {
                "breakdown": br,
                "instrument": instr,
                "xirr_pct": xirr_pct,
                "weight_pct": weight_pct,
                "ltp": price,
                "price_is_stale": is_stale,
                "is_old": is_old,
            }
        )

    # --- Sort ---------------------------------------------------------------
    def _key(row):
        br = row["breakdown"]
        val = {
            "name": (row["instrument"].name or "").lower(),
            "qty": br.qty_held,
            "invested": br.invested_open,
            "current_value": br.current_value or 0,
            "dividends": br.dividends,
            "xirr": row["xirr_pct"] if row["xirr_pct"] is not None else -1e9,
            "unrealised": float(br.unrealised_pnl) if br.unrealised_pnl is not None else -1e18,
            "weight": row["weight_pct"] if row["weight_pct"] is not None else -1e9,
        }.get(sort, (row["instrument"].name or "").lower())
        return val

    try:
        rows.sort(key=_key, reverse=(sort_dir == "desc"))
    except TypeError:
        # Mixed Decimal / int comparisons from empty-breakdown rows; ignore
        # sort errors rather than fail the page.
        rows.sort(key=lambda r: (r["instrument"].name or "").lower())

    summary_xirr_pct = float(summary.xirr) * 100 if summary.xirr is not None else None
    unrealised = summary.total_unrealised

    # Per-broker invested sub-totals (only displayed when no broker filter is
    # active — gives a sanity glance across demats without forcing a filter).
    broker_strip: list[dict] = []
    if ba_filter is None and all_broker_accounts:
        from core.services.investments import portfolio_summary as _ps

        for ba in all_broker_accounts:
            sub = _ps(
                profile,
                broker_account=ba,
                kind=selected_kind or None,
                price_lookup=price_lookup,
            )
            if sub.total_invested_open > 0 or sub.total_current_value > 0:
                broker_strip.append(
                    {
                        "broker": ba,
                        "invested": sub.total_invested_open,
                        "current_value": sub.total_current_value,
                    }
                )

    # Realised P&L grouped by Indian Financial Year (Apr–Mar). Tax-planning
    # signal that XIRR / lifetime totals don't capture.
    from core.services.investments import realised_by_fy as _realised_by_fy

    fy_rows = _realised_by_fy(
        profile, broker_account=ba_filter, kind=selected_kind or None
    )

    from core.models import UserPreferences as _UP

    prefs = _UP.objects.filter(user=profile.user).first()

    from urllib.parse import urlencode

    filter_params = {
        "broker": str(selected_broker_account_id) if selected_broker_account_id else "",
        "kind": selected_kind,
    }
    if include_old:
        filter_params["include_old"] = "1"
    sort_qs_extra = urlencode({k: v for k, v in filter_params.items() if v})

    context = {
        "active": "investments",
        "profile": profile,
        "base_currency": profile.user.base_currency,
        "summary": summary,
        "summary_xirr_pct": summary_xirr_pct,
        "unrealised": unrealised,
        "rows": rows,
        "broker_accounts": all_broker_accounts,
        "broker_strip": broker_strip,
        "selected_broker_account_id": selected_broker_account_id,
        "selected_kind": selected_kind,
        "kinds": InstrumentKind.choices,
        "sort": sort,
        "sort_dir": sort_dir,
        "include_old": include_old,
        "sort_qs_extra": sort_qs_extra,
        "stale_count": stale_count,
        "fy_rows": fy_rows,
        "live_price_enabled": bool(prefs and prefs.live_price_enabled),
        "last_price_refresh_at": prefs.last_price_refresh_at if prefs else None,
    }
    return render(request, "wealth/investments/list.html", context)


@require_POST
def investments_refresh_prices(request: HttpRequest) -> HttpResponse:
    """Manually trigger a price refresh and redirect back to the list."""
    profile = Profile.objects.filter(is_default=True).select_related("user").first()
    if profile is None:
        return redirect(reverse("investments_list"))
    from core.services.prices import refresh_prices as _refresh_prices

    try:
        result = _refresh_prices(profile, force=True)
        ok_count = result.ticks_written
        scanned = result.instruments_scanned
        if ok_count:
            messages.success(
                request, f"Refreshed {ok_count} price(s) across {scanned} instrument(s)."
            )
        else:
            messages.info(
                request,
                f"No prices fetched (scanned {scanned} instruments). "
                "Check that instruments have an exchange_symbol set, "
                "or that the NSE / AMFI feed is reachable.",
            )
        for err in result.errors[:3]:
            messages.warning(request, err)
    except Exception as exc:  # noqa: BLE001
        messages.error(request, f"Price refresh failed: {exc}")
    return redirect(reverse("investments_list"))


def instrument_detail(request: HttpRequest, instrument_id: int) -> HttpResponse:
    profile = Profile.objects.filter(is_default=True).select_related("user").first()
    if profile is None:
        raise Http404("Profile not configured")
    instrument = get_object_or_404(Instrument, id=instrument_id, profile=profile)

    from datetime import date, timedelta
    from decimal import Decimal

    from core.services.investments import (
        _indian_fy_label,
        instrument_breakdown,
        realised_by_fy,
    )
    from core.services.lots import build_lots
    from core.services.prices import latest_price as _latest_price

    price_lookup = _make_price_lookup(profile)

    trades = list(
        StockTrade.objects.filter(profile=profile, instrument=instrument)
        .select_related("broker_account")
        .order_by("trade_date", "id")
    )
    dividends = list(
        DividendRecord.objects.filter(profile=profile, instrument=instrument)
        .select_related("broker_account")
        .order_by("ex_date")
    )
    actions = list(
        CorporateAction.objects.filter(profile=profile, instrument=instrument).order_by("ex_date")
    )

    # strict=False so a partial tradebook window (SELL with no prior BUY in
    # the visible history) synthesises a zero-cost opening balance instead of
    # crashing the detail page. The template flags the book with a banner.
    books = build_lots(trades, actions, strict=False)

    breakdown = instrument_breakdown(profile, instrument, price_lookup=price_lookup)
    price, stale = _latest_price(instrument)

    xirr_pct = float(breakdown.xirr) * 100 if breakdown.xirr is not None else None

    # Per-lot tax-status enrichment. ``price`` is in the instrument's currency;
    # for the simple INR-equity case it is also the base. Cross-currency users
    # already see per-lot rows in cost terms, so showing unrealised values only
    # when we trivially have an INR/INR pair keeps this honest.
    today = date.today()
    show_lot_pricing = price is not None and instrument.currency == profile.user.base_currency
    open_lot_rows: list[dict] = []
    realised_lots: list[dict] = []
    ba_cache: dict[int, BrokerAccount | None] = {}
    for (ba_id, _), book in sorted(books.items()):
        if ba_id not in ba_cache:
            ba_cache[ba_id] = BrokerAccount.objects.filter(id=ba_id).first()
        ba = ba_cache[ba_id]
        for lot in book.open_lots:
            days = (today - lot.opened_on).days
            current_value = lot.qty_remaining * price if show_lot_pricing else None
            unrealised = (
                lot.qty_remaining * (price - lot.cost_per_unit)
                if show_lot_pricing
                else None
            )
            open_lot_rows.append(
                {
                    "lot": lot,
                    "broker": ba,
                    "days": days,
                    "days_to_ltcg": max(0, 366 - days) if days <= 365 else 0,
                    "invested": lot.qty_remaining * lot.cost_per_unit,
                    "current_value": current_value,
                    "unrealised": unrealised,
                    "long_term": days > 365,
                }
            )
        for r in book.realised:
            buy_price_per_unit = (r.buy_cost / r.qty) if r.qty else None
            sell_price_per_unit = (r.sell_proceeds / r.qty) if r.qty else None
            realised_lots.append(
                {
                    "realised": r,
                    "broker": ba,
                    "buy_price_per_unit": buy_price_per_unit,
                    "sell_price_per_unit": sell_price_per_unit,
                }
            )
    open_lot_rows.sort(key=lambda r: r["lot"].opened_on)
    realised_lots.sort(key=lambda row: row["realised"].close_date, reverse=True)

    # Distinct broker accounts that ever touched this instrument (drives the
    # per-section "Demat account" filter dropdowns).
    instrument_brokers = sorted(
        {t.broker_account for t in trades if t.broker_account is not None},
        key=lambda b: (b.broker_key, b.account_label),
    )

    # Dividends grouped by Indian FY for the mini-bar chart, plus TTM yield.
    # Each dividend row gets annotated with ``eff_pay_date`` (real if known,
    # else ex_date + 35d) and a ``pay_date_estimated`` flag so the template
    # can show a concrete date with an "approx" hint when the broker
    # source (e.g. Aionion XLSX) doesn't export pay dates.
    fy_dividends: dict[str, Decimal] = {}
    ttm_window_start = today - timedelta(days=365)
    ttm_dividends_total = Decimal(0)
    for d in dividends:
        eff = d.pay_date or (d.ex_date + timedelta(days=35))
        d.eff_pay_date = eff
        d.pay_date_estimated = d.pay_date is None
        fy = _indian_fy_label(eff)
        fy_dividends[fy] = fy_dividends.get(fy, Decimal(0)) + d.amount_net
        if eff >= ttm_window_start:
            ttm_dividends_total += d.amount_net
    fy_dividend_rows = [{"fy": fy, "amount": amt} for fy, amt in sorted(fy_dividends.items())]

    ttm_yield_pct: float | None = None
    if breakdown.current_value is not None and breakdown.current_value > 0:
        ttm_yield_pct = float(ttm_dividends_total / breakdown.current_value) * 100

    fy_rows = realised_by_fy(profile, instrument=instrument)

    context = {
        "active": "investments",
        "profile": profile,
        "base_currency": profile.user.base_currency,
        "instrument": instrument,
        "trades": trades,
        "dividends": dividends,
        "actions": actions,
        "open_lot_rows": open_lot_rows,
        "instrument_brokers": instrument_brokers,
        "realised_lots": realised_lots,
        "breakdown": breakdown,
        "xirr_pct": xirr_pct,
        "ltp": price,
        "price_is_stale": stale,
        "fy_dividend_rows": fy_dividend_rows,
        "fy_rows": fy_rows,
        "ttm_yield_pct": ttm_yield_pct,
    }
    return render(request, "wealth/investments/detail.html", context)
