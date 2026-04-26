from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from core.models import (
    AllocationTarget,
    Asset,
    BrokerAccount,
    Category,
    CorporateAction,
    DividendRecord,
    EssentialsState,
    FxRate,
    Goal,
    ImportJob,
    Instrument,
    Liability,
    PriceTick,
    Profile,
    RecurringRule,
    Snapshot,
    StockTrade,
    Tag,
    Transaction,
    User,
    UserPreferences,
)


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Finance preferences", {"fields": ("base_currency", "theme", "app_lock_hash")}),
    )
    list_display = ("username", "email", "base_currency", "is_staff")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "is_default", "created_at")
    list_filter = ("is_default",)
    search_fields = ("name", "user__username")


@admin.register(FxRate)
class FxRateAdmin(admin.ModelAdmin):
    list_display = ("from_ccy", "to_ccy", "rate", "fetched_at", "user")
    list_filter = ("from_ccy", "to_ccy")


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("label", "profile")
    search_fields = ("label",)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "type", "profile", "is_exempt", "is_custom")
    list_filter = ("type", "is_exempt", "is_custom")
    search_fields = ("name",)


@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "subtype", "currency", "current_value", "updated_at")
    list_filter = ("category", "currency", "exclude_from_allocation")
    search_fields = ("name", "instrument_symbol")
    autocomplete_fields = ("tags",)


@admin.register(Liability)
class LiabilityAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "currency", "outstanding_amount", "updated_at")
    list_filter = ("category", "currency")
    search_fields = ("name",)
    autocomplete_fields = ("tags",)


@admin.register(RecurringRule)
class RecurringRuleAdmin(admin.ModelAdmin):
    list_display = ("profile", "cadence", "start_date", "last_generated")
    list_filter = ("cadence",)


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ("date", "type", "description", "amount", "currency", "category")
    list_filter = ("type", "currency", "date")
    search_fields = ("description", "notes")
    date_hierarchy = "date"
    autocomplete_fields = ("tags", "category")


@admin.register(Snapshot)
class SnapshotAdmin(admin.ModelAdmin):
    list_display = ("taken_at", "source", "profile", "net_worth", "base_currency")
    list_filter = ("source", "base_currency")
    readonly_fields = ("taken_at", "breakdown_json")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = ("name", "target_amount", "currency", "target_date", "linked_asset_class")
    list_filter = ("linked_asset_class", "currency")
    search_fields = ("name",)


@admin.register(AllocationTarget)
class AllocationTargetAdmin(admin.ModelAdmin):
    list_display = ("preset_name", "profile")


@admin.register(EssentialsState)
class EssentialsStateAdmin(admin.ModelAdmin):
    list_display = (
        "profile",
        "emergency_fund_target_months",
        "term_cover_amount",
        "health_cover_amount",
    )


@admin.register(ImportJob)
class ImportJobAdmin(admin.ModelAdmin):
    list_display = ("filename", "source", "scope", "mode", "rows_imported", "status", "created_at")
    list_filter = ("source", "scope", "mode", "status")
    readonly_fields = ("created_at", "log")


# ---------------------------------------------------------------------------
# Phase A+ investments admin
# ---------------------------------------------------------------------------


@admin.register(UserPreferences)
class UserPreferencesAdmin(admin.ModelAdmin):
    list_display = ("user", "live_price_enabled", "last_price_refresh_at")


@admin.register(BrokerAccount)
class BrokerAccountAdmin(admin.ModelAdmin):
    list_display = (
        "account_label",
        "broker_key",
        "profile",
        "client_code",
        "base_currency",
        "created_at",
    )
    list_filter = ("broker_key", "base_currency")
    search_fields = ("account_label", "client_code")


@admin.register(Instrument)
class InstrumentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "isin",
        "exchange_symbol",
        "kind",
        "currency",
        "needs_review",
        "updated_at",
    )
    list_filter = ("kind", "currency", "needs_review")
    search_fields = ("name", "isin", "exchange_symbol", "amfi_code")


@admin.register(StockTrade)
class StockTradeAdmin(admin.ModelAdmin):
    list_display = (
        "trade_date",
        "side",
        "instrument",
        "quantity",
        "price",
        "net_amount",
        "broker_account",
        "off_market",
    )
    list_filter = ("side", "off_market", "broker_account__broker_key", "trade_date")
    search_fields = (
        "instrument__name",
        "instrument__isin",
        "instrument__exchange_symbol",
        "trade_ref",
    )
    date_hierarchy = "trade_date"
    readonly_fields = ("created_at", "raw_row_json")
    autocomplete_fields = ("instrument",)


@admin.register(DividendRecord)
class DividendRecordAdmin(admin.ModelAdmin):
    list_display = (
        "ex_date",
        "pay_date",
        "instrument",
        "amount_net",
        "tds",
        "source",
        "broker_account",
    )
    list_filter = ("source", "broker_account__broker_key", "ex_date")
    search_fields = ("instrument__name", "instrument__isin")
    date_hierarchy = "ex_date"
    autocomplete_fields = ("instrument",)


@admin.register(CorporateAction)
class CorporateActionAdmin(admin.ModelAdmin):
    list_display = (
        "ex_date",
        "action_type",
        "instrument",
        "ratio_numerator",
        "ratio_denominator",
        "units_added",
        "broker_account",
    )
    list_filter = ("action_type", "ex_date")
    search_fields = ("instrument__name", "instrument__isin", "notes")
    date_hierarchy = "ex_date"
    autocomplete_fields = ("instrument", "new_instrument")


@admin.register(PriceTick)
class PriceTickAdmin(admin.ModelAdmin):
    list_display = ("instrument", "as_of", "price", "currency", "source", "fetched_at")
    list_filter = ("source", "currency")
    search_fields = ("instrument__name", "instrument__isin")
    date_hierarchy = "as_of"
    autocomplete_fields = ("instrument",)
