"""All data models for PersonalFinanceTracker.

Kept in one file per CLAUDE.md "single Django project" convention. Sections:

1.  Auth + identity     — User, Profile, FxRate, UserPreferences
2.  Tags + categories   — Tag, Category
3.  Wealth              — Asset, Liability
4.  Transactions        — Transaction, RecurringRule
5.  Snapshots           — Snapshot
6.  Goals               — Goal
7.  Allocation          — AllocationTarget
8.  Essentials          — EssentialsState
9.  Imports             — ImportJob
10. Investments         — BrokerAccount, Instrument, StockTrade,
                          DividendRecord, CorporateAction, PriceTick

The schema mirrors `SPEC.md §4`. Decimal money columns use `max_digits=20, decimal_places=4`
everywhere to meet the money-discipline convention. Every row except User, FxRate, and the
global-ish PriceTick scopes to a `Profile` (multi-profile-ready from day 1 per CLAUDE.md
convention #3).
"""

from django.contrib.auth.models import AbstractUser
from django.db import models

# ---------------------------------------------------------------------------
# 1. Auth + identity
# ---------------------------------------------------------------------------


class User(AbstractUser):
    """Single local user. Email is optional (no cloud auth at v1)."""

    base_currency = models.CharField(max_length=3, default="INR")
    theme = models.CharField(
        max_length=10,
        choices=[("light", "Light"), ("dark", "Dark"), ("system", "System")],
        default="light",
    )
    app_lock_hash = models.CharField(max_length=255, blank=True, default="")

    def __str__(self) -> str:
        return self.username


class Profile(models.Model):
    """A scoping container for every financial row. MVP exposes only the default profile."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="profiles")
    name = models.CharField(max_length=100)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "name"], name="uniq_profile_per_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user.username}/{self.name}"


class FxRate(models.Model):
    """Cached FX rate for converting from_ccy -> to_ccy. One row per pair; refresh overwrites."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="fx_rates")
    from_ccy = models.CharField(max_length=3)
    to_ccy = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=20, decimal_places=8)
    fetched_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "from_ccy", "to_ccy"], name="uniq_fx_pair_per_user"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.from_ccy}->{self.to_ccy} @ {self.rate}"


# ---------------------------------------------------------------------------
# 2. Tags + categories
# ---------------------------------------------------------------------------


class Tag(models.Model):
    """Free-form label shared by Asset, Liability, Transaction."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="tags")
    label = models.CharField(max_length=50)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["profile", "label"], name="uniq_tag_per_profile"),
        ]

    def __str__(self) -> str:
        return self.label


class TxType(models.TextChoices):
    EXPENSE = "EXPENSE", "Expense"
    INCOME = "INCOME", "Income"


class Category(models.Model):
    """Transaction category. Rows (not an enum) so custom categories don't orphan on rename."""

    profile = models.ForeignKey(
        Profile,
        on_delete=models.CASCADE,
        related_name="categories",
        null=True,
        blank=True,
        help_text="NULL = system default (shared across profiles).",
    )
    type = models.CharField(max_length=10, choices=TxType.choices)
    name = models.CharField(max_length=80)
    is_exempt = models.BooleanField(
        default=False, help_text="If true, transactions in this category are excluded from totals."
    )
    is_custom = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "type", "name"], name="uniq_category_per_scope"
            ),
        ]
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return f"[{self.type}] {self.name}"


# ---------------------------------------------------------------------------
# 3. Wealth
# ---------------------------------------------------------------------------


class AssetCategory(models.TextChoices):
    EQUITY = "EQUITY", "Stocks & Equity"
    GOLD = "GOLD", "Gold & Silver"
    BONDS_DEBT = "BONDS_DEBT", "Bonds & Debt"
    REAL_ESTATE = "REAL_ESTATE", "Real Estate"
    RETIREMENT = "RETIREMENT", "Retirement"
    CASH = "CASH", "Cash & Savings"
    ALTERNATIVES = "ALTERNATIVES", "Alternatives"
    OTHER = "OTHER", "Other"


class Geography(models.TextChoices):
    INDIA = "IN", "India"
    INTL = "INTL", "International"
    MIXED = "MIXED", "Mixed"


class Asset(models.Model):
    """A single holding. Per-subtype field variants are documented in `core/subtypes.py`."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="assets")
    category = models.CharField(max_length=20, choices=AssetCategory.choices)
    subtype = models.CharField(max_length=40, help_text="e.g. DIRECT_STOCK, FD, PPF")
    name = models.CharField(max_length=200)
    currency = models.CharField(max_length=3, default="INR")

    current_value = models.DecimalField(max_digits=20, decimal_places=4)
    cost_basis = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)

    start_date = models.DateField(null=True, blank=True)
    maturity_date = models.DateField(null=True, blank=True)
    interest_rate = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)

    geography = models.CharField(max_length=10, choices=Geography.choices, blank=True, default="")
    sub_class = models.CharField(max_length=40, blank=True, default="")
    weight = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)

    live_price_enabled = models.BooleanField(default=False)
    instrument_symbol = models.CharField(max_length=40, blank=True, default="")
    instrument = models.ForeignKey(
        "Instrument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assets",
        help_text="Links equity / MF assets to the canonical Instrument row driving XIRR.",
    )

    notes = models.TextField(blank=True, default="")
    exclude_from_allocation = models.BooleanField(default=False)

    tags = models.ManyToManyField(Tag, related_name="assets", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["profile", "category"])]

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"


class LiabilityCategory(models.TextChoices):
    HOME_LOAN = "HOME_LOAN", "Home Loan"
    VEHICLE_LOAN = "VEHICLE_LOAN", "Vehicle Loan"
    PERSONAL_LOAN = "PERSONAL_LOAN", "Personal Loan"
    EDUCATION_LOAN = "EDUCATION_LOAN", "Education Loan"
    CREDIT_CARD = "CREDIT_CARD", "Credit Card"
    GOLD_LOAN = "GOLD_LOAN", "Gold Loan"
    BUSINESS_LOAN = "BUSINESS_LOAN", "Business Loan"
    FRIENDS_FAMILY = "FRIENDS_FAMILY", "Friends / Family"
    OTHER = "OTHER", "Other"


class Liability(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="liabilities")
    category = models.CharField(max_length=20, choices=LiabilityCategory.choices)
    name = models.CharField(max_length=200)
    currency = models.CharField(max_length=3, default="INR")

    outstanding_amount = models.DecimalField(max_digits=20, decimal_places=4)
    interest_rate = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    monthly_emi = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default="")

    tags = models.ManyToManyField(Tag, related_name="liabilities", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"


# ---------------------------------------------------------------------------
# 4. Transactions
# ---------------------------------------------------------------------------


class RecurringRule(models.Model):
    """Template for automatically-generated upcoming transactions (Phase 3+)."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="recurring_rules")
    template_json = models.JSONField()
    cadence = models.CharField(max_length=40, help_text='e.g. "monthly", "weekly", or a CRON.')
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    last_generated = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"RecurringRule[{self.cadence}] from {self.start_date}"


class Transaction(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="transactions")
    type = models.CharField(max_length=10, choices=TxType.choices)
    date = models.DateField()
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="transactions")
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3, default="INR")
    notes = models.TextField(blank=True, default="")
    recurring_rule = models.ForeignKey(
        RecurringRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    tags = models.ManyToManyField(Tag, related_name="transactions", blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "date"]),
            models.Index(fields=["profile", "category"]),
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.type} {self.description} {self.amount}{self.currency}"


# ---------------------------------------------------------------------------
# 5. Snapshots (immutable)
# ---------------------------------------------------------------------------


class SnapshotSource(models.TextChoices):
    MANUAL = "manual", "Manual"
    AUTO = "auto", "Auto"


class Snapshot(models.Model):
    """Immutable point-in-time record of net worth. Never recompute from current data."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="snapshots")
    taken_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(
        max_length=10, choices=SnapshotSource.choices, default=SnapshotSource.MANUAL
    )
    base_currency = models.CharField(max_length=3)
    net_worth = models.DecimalField(max_digits=20, decimal_places=4)
    total_assets = models.DecimalField(max_digits=20, decimal_places=4)
    total_liabilities = models.DecimalField(max_digits=20, decimal_places=4)
    breakdown_json = models.JSONField(help_text="Serialized allocation/holdings at snapshot time.")

    class Meta:
        indexes = [models.Index(fields=["profile", "taken_at"])]

    def __str__(self) -> str:
        return f"Snapshot({self.taken_at:%Y-%m-%d}, NW={self.net_worth})"


# ---------------------------------------------------------------------------
# 6. Goals
# ---------------------------------------------------------------------------


class Goal(models.Model):
    """A savings target, optionally linked to an asset class or a list of specific assets."""

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="goals")
    name = models.CharField(max_length=200)
    template_id = models.CharField(
        max_length=40,
        blank=True,
        default="",
        help_text='Optional preset key, e.g. "RETIREMENT" or "EMERGENCY".',
    )
    target_amount = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3, default="INR")
    target_date = models.DateField()
    linked_asset_class = models.CharField(
        max_length=40,
        default="NET_WORTH",
        help_text='e.g. "NET_WORTH", "EQUITY", or a custom class id.',
    )
    linked_asset_ids = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.name} ({self.target_amount} {self.currency} by {self.target_date})"


# ---------------------------------------------------------------------------
# 7. Allocation target
# ---------------------------------------------------------------------------


class AllocationTarget(models.Model):
    """User-configured target allocation per class, as percentages."""

    profile = models.ForeignKey(
        Profile, on_delete=models.CASCADE, related_name="allocation_targets"
    )
    preset_name = models.CharField(max_length=60, default="Default")
    percent_by_class = models.JSONField(
        help_text='e.g. {"EQUITY": 55, "BONDS_DEBT": 20, "GOLD": 10, "ALTERNATIVES": 10, "REAL_ESTATE": 5}',
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "preset_name"], name="uniq_alloc_preset_per_profile"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.preset_name} @ {self.profile}"


# ---------------------------------------------------------------------------
# 8. Essentials
# ---------------------------------------------------------------------------


class EssentialsState(models.Model):
    """Inputs for the financial-health score (one row per profile)."""

    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="essentials")
    emergency_fund_target_months = models.IntegerField(default=6)
    term_cover_amount = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    term_cover_target_multiplier = models.IntegerField(
        default=10, help_text="target = annual_income * multiplier"
    )
    health_cover_amount = models.DecimalField(
        max_digits=20, decimal_places=4, null=True, blank=True
    )
    health_cover_target = models.DecimalField(max_digits=20, decimal_places=4, default=1_000_000)

    def __str__(self) -> str:
        return f"Essentials({self.profile})"


# ---------------------------------------------------------------------------
# 9. Import jobs
# ---------------------------------------------------------------------------


class ImportStatus(models.TextChoices):
    RUNNING = "running", "Running"
    OK = "ok", "OK"
    ERROR = "error", "Error"


class ImportJob(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="import_jobs")
    source = models.CharField(max_length=40, help_text='e.g. "generic_csv", "zerodha" (Phase 6+).')
    scope = models.CharField(max_length=20, help_text='"assets" | "transactions"')
    mode = models.CharField(max_length=20, help_text='"append" | "update_by_name"')
    filename = models.CharField(max_length=255)
    rows_imported = models.IntegerField(default=0)
    status = models.CharField(max_length=10, choices=ImportStatus.choices)
    log = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Import[{self.source}/{self.scope}] {self.filename} {self.status}"


# ---------------------------------------------------------------------------
# 10. Investments (Phase A: data model only; services in core/services/*)
# ---------------------------------------------------------------------------


class UserPreferences(models.Model):
    """User-level prefs that aren't part of the login identity.

    Separated from ``User`` to avoid churn on the auth table. Today only one
    field matters -- the opt-in toggle for fetching live prices from
    NSE/BSE/AMFI. Default is off per CLAUDE.md §6 "no telemetry by default".
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    live_price_enabled = models.BooleanField(default=False)
    last_price_refresh_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Preferences({self.user.username})"


class BrokerKind(models.TextChoices):
    ZERODHA = "zerodha", "Zerodha"
    CHOLA = "chola", "Cholamandalam Securities"
    AIONION = "aionion", "Aionion"


class BrokerAccount(models.Model):
    """One demat / broker account held by the user.

    Same ISIN held in two brokers is two independent positions for FIFO
    purposes -- lots are scoped per ``BrokerAccount`` so a SELL on broker A
    never draws down a BUY on broker B.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="broker_accounts")
    broker_key = models.CharField(max_length=20, choices=BrokerKind.choices)
    account_label = models.CharField(
        max_length=80,
        help_text="Free-form label disambiguating multiple accounts with the same broker.",
    )
    client_code = models.CharField(max_length=40, blank=True, default="")
    base_currency = models.CharField(max_length=3, default="INR")
    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "broker_key", "account_label"],
                name="uniq_broker_account_per_profile",
            ),
        ]
        indexes = [models.Index(fields=["profile", "broker_key"])]

    def __str__(self) -> str:
        return f"{self.get_broker_key_display()} / {self.account_label}"


class InstrumentKind(models.TextChoices):
    STOCK = "STOCK", "Equity stock"
    MF = "MF", "Mutual fund"


class Instrument(models.Model):
    """Canonical per-ISIN row. Shared by all BrokerAccounts in a profile so
    the same holding in Zerodha + Chola dedupes to one instrument.

    ``isin_aliases`` lets a merged/renamed ISIN be absorbed by the new row
    without losing history -- future imports check aliases before creating
    a new Instrument.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="instruments")
    isin = models.CharField(max_length=12, blank=True, default="")
    exchange_symbol = models.CharField(max_length=40, blank=True, default="")
    name = models.CharField(max_length=200)
    kind = models.CharField(max_length=8, choices=InstrumentKind.choices)
    currency = models.CharField(max_length=3, default="INR")
    amfi_code = models.CharField(max_length=12, blank=True, default="")
    mf_scheme_code = models.CharField(max_length=20, blank=True, default="")
    isin_aliases = models.JSONField(
        default=list,
        blank=True,
        help_text="List of prior ISINs for this instrument after corp actions.",
    )
    needs_review = models.BooleanField(
        default=False,
        help_text="Set when auto-created from Asset backfill without a confirmed ISIN.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["profile", "isin"],
                name="uniq_instrument_isin_per_profile",
                condition=models.Q(isin__gt=""),
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "kind"]),
            models.Index(fields=["profile", "exchange_symbol"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} [{self.isin or 'no-isin'}]"


class TradeSide(models.TextChoices):
    BUY = "BUY", "Buy"
    SELL = "SELL", "Sell"


class StockTrade(models.Model):
    """Immutable buy/sell event on a specific BrokerAccount.

    ``net_amount`` is the signed INR-equivalent cash movement after charges
    (BUY < 0, SELL > 0) and is precomputed at import time so the XIRR
    builder never has to rederive it. ``trade_ref`` is the broker-native
    trade id where available; synthesised for brokers that don't provide
    one (e.g. Chola PDF) -- the uniqueness constraint makes re-imports
    idempotent.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="stock_trades")
    broker_account = models.ForeignKey(
        BrokerAccount, on_delete=models.CASCADE, related_name="stock_trades"
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="stock_trades"
    )
    trade_date = models.DateField()
    exec_time = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Intra-day order execution time for FIFO tie-breaking.",
    )
    side = models.CharField(max_length=4, choices=TradeSide.choices)
    quantity = models.DecimalField(max_digits=20, decimal_places=8)
    price = models.DecimalField(max_digits=20, decimal_places=4)
    brokerage = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    stt = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    gst = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    stamp_duty = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    sebi_charges = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    exchange_charges = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    total_charges = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    net_amount = models.DecimalField(
        max_digits=20,
        decimal_places=4,
        help_text="Signed cashflow: BUY is negative, SELL is positive.",
    )
    currency = models.CharField(max_length=3, default="INR")
    off_market = models.BooleanField(default=False)
    trade_ref = models.CharField(max_length=80)
    raw_row_json = models.JSONField(default=dict, blank=True)
    import_job = models.ForeignKey(
        ImportJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_trades",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker_account", "trade_ref"],
                name="uniq_trade_ref_per_broker_account",
            ),
        ]
        indexes = [
            models.Index(fields=["profile", "trade_date"]),
            models.Index(fields=["broker_account", "instrument", "trade_date"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.trade_date} {self.side} {self.quantity} {self.instrument.name} "
            f"@ {self.price} ({self.broker_account.broker_key})"
        )


class DividendSource(models.TextChoices):
    ZERODHA_XLSX = "zerodha_xlsx", "Zerodha XLSX"
    CHOLA_PDF = "chola_pdf", "Chola PDF"
    AIONION_XLSX = "aionion_xlsx", "Aionion XLSX"


class DividendRecord(models.Model):
    """Cash dividend paid on an instrument.

    XIRR uses ``pay_date`` when available, otherwise falls back to
    ``ex_date + 35 days`` (Zerodha's own 30-45 day window midpoint).
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="dividend_records")
    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.PROTECT,
        related_name="dividend_records",
    )
    instrument = models.ForeignKey(
        Instrument, on_delete=models.PROTECT, related_name="dividend_records"
    )
    ex_date = models.DateField()
    pay_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date cash hit the bank; may be unknown (e.g. Zerodha XLSX only gives ex-date).",
    )
    amount_gross = models.DecimalField(max_digits=20, decimal_places=4)
    tds = models.DecimalField(max_digits=20, decimal_places=4, default=0)
    amount_net = models.DecimalField(max_digits=20, decimal_places=4)
    dividend_per_share = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    quantity = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    currency = models.CharField(max_length=3, default="INR")
    source = models.CharField(max_length=20, choices=DividendSource.choices)
    raw_row_json = models.JSONField(default=dict, blank=True)
    import_job = models.ForeignKey(
        ImportJob,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="dividend_records",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "profile",
                    "broker_account",
                    "instrument",
                    "ex_date",
                    "amount_gross",
                ],
                name="uniq_dividend_per_ex_date",
            ),
        ]
        indexes = [models.Index(fields=["profile", "ex_date"])]

    def __str__(self) -> str:
        return f"Dividend {self.instrument.name} {self.amount_net} on {self.ex_date}"


class CorporateActionType(models.TextChoices):
    SPLIT = "SPLIT", "Stock split"
    BONUS = "BONUS", "Bonus issue"
    MERGER = "MERGER", "Merger"
    BUYBACK = "BUYBACK", "Buyback"
    DEMERGER = "DEMERGER", "Demerger"
    ISIN_CHANGE = "ISIN_CHANGE", "ISIN change"


class CorporateAction(models.Model):
    """Non-trade event that adjusts lot quantities or rewrites the instrument.

    For SPLIT/BONUS, ``ratio_numerator/ratio_denominator`` capture the
    ratio directly (e.g. 1:10 split -> 10/1). When the source only reports
    ``units_added`` (Chola PDFs do this), the lot engine infers the ratio
    from the broker's holdings on ``ex_date``.
    """

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="corporate_actions")
    instrument = models.ForeignKey(
        Instrument, on_delete=models.CASCADE, related_name="corporate_actions"
    )
    broker_account = models.ForeignKey(
        BrokerAccount,
        on_delete=models.PROTECT,
        related_name="corporate_actions",
        help_text=(
            "Demat account this action was reported on. Each broker that "
            "holds the instrument is recorded separately so per-account "
            "units_added stays attributable."
        ),
    )
    action_type = models.CharField(max_length=16, choices=CorporateActionType.choices)
    ex_date = models.DateField()
    ratio_numerator = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    ratio_denominator = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    units_added = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        null=True,
        blank=True,
        help_text="When the source reports added qty directly (Chola-style SPLIT).",
    )
    new_instrument = models.ForeignKey(
        Instrument,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corporate_actions_as_new",
        help_text="For MERGER / DEMERGER / ISIN_CHANGE.",
    )
    cash_component = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    source = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["broker_account", "instrument", "action_type", "ex_date"],
                name="uniq_corp_action_per_instrument_date",
            ),
        ]
        indexes = [models.Index(fields=["instrument", "ex_date"])]

    def __str__(self) -> str:
        return f"{self.action_type} {self.instrument.name} on {self.ex_date}"


class PriceSource(models.TextChoices):
    NSE_BHAVCOPY = "nse_bhavcopy", "NSE bhavcopy"
    BSE_BHAVCOPY = "bse_bhavcopy", "BSE bhavcopy"
    AMFI = "amfi", "AMFI NAV feed"
    MANUAL = "manual", "Manual"


class PriceTick(models.Model):
    """Latest-known price for an Instrument from a given source."""

    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="price_ticks")
    price = models.DecimalField(max_digits=20, decimal_places=4)
    currency = models.CharField(max_length=3, default="INR")
    source = models.CharField(max_length=20, choices=PriceSource.choices)
    as_of = models.DateField(help_text="Business date the price applies to.")
    fetched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["instrument", "source", "as_of"],
                name="uniq_price_tick_per_instrument_source_date",
            ),
        ]
        indexes = [models.Index(fields=["instrument", "-as_of"])]

    def __str__(self) -> str:
        return f"{self.instrument.name} {self.price} {self.currency} @ {self.as_of}"
