from django.urls import path
from django.views.generic import RedirectView

from core import views

urlpatterns = [
    path("", views.hello, name="hello"),
    path("auth/pin", views.pin_set, name="pin_set"),
    path("auth/unlock", views.pin_unlock, name="pin_unlock"),
    # Wealth: Assets
    path("wealth/assets", views.asset_list, name="asset_list"),
    path("wealth/assets/new", views.asset_new, name="asset_new"),
    path("wealth/assets/<int:asset_id>/edit", views.asset_edit, name="asset_edit"),
    path("wealth/assets/<int:asset_id>/delete", views.asset_delete, name="asset_delete"),
    # Wealth: Net Worth + Allocation
    path("wealth/snapshots", views.snapshots_view, name="snapshots"),
    path("wealth/snapshots/new", views.snapshot_create, name="snapshot_create"),
    path("wealth/allocation", views.allocation_view, name="allocation"),
    # Wealth: Investments (Phase D)
    path("wealth/investments/", views.investments_list, name="investments_list"),
    path(
        "wealth/investments/refresh-prices",
        views.investments_refresh_prices,
        name="investments_refresh_prices",
    ),
    path(
        "wealth/investments/<int:instrument_id>/",
        views.instrument_detail,
        name="instrument_detail",
    ),
    # Wealth: Liabilities
    path("wealth/liabilities", views.liability_list, name="liability_list"),
    path("wealth/liabilities/new", views.liability_new, name="liability_new"),
    path(
        "wealth/liabilities/<int:liability_id>/edit",
        views.liability_edit,
        name="liability_edit",
    ),
    path(
        "wealth/liabilities/<int:liability_id>/delete",
        views.liability_delete,
        name="liability_delete",
    ),
    # Money: Transactions
    path(
        "money/",
        RedirectView.as_view(url="/money/expenses", permanent=False),
        name="money_root",
    ),
    path("money/insights", views.insights_placeholder, name="insights"),
    path(
        "money/transactions/<int:tx_id>/edit",
        views.transaction_edit,
        name="transaction_edit",
    ),
    path(
        "money/transactions/<int:tx_id>/delete",
        views.transaction_delete,
        name="transaction_delete",
    ),
    path(
        "money/<str:segment>/new",
        views.transaction_new,
        name="transaction_new",
    ),
    path(
        "money/<str:segment>",
        views.transaction_list,
        name="transaction_list",
    ),
    # Essentials + Goals
    path("essentials/", views.essentials_view, name="essentials"),
    path("essentials/update", views.essentials_update, name="essentials_update"),
    path("goals/", views.goal_list, name="goal_list"),
    path("goals/new", views.goal_new, name="goal_new"),
    path("goals/inflation", views.inflation_calculator, name="inflation_calculator"),
    path("goals/<int:goal_id>/edit", views.goal_edit, name="goal_edit"),
    path("goals/<int:goal_id>/delete", views.goal_delete, name="goal_delete"),
    # Settings
    path("settings/", views.settings_redirect, name="settings_root"),
    path("settings/preferences", views.preferences, name="preferences"),
    path(
        "settings/categories/<int:cat_id>/toggle-exempt",
        views.category_toggle_exempt,
        name="category_toggle_exempt",
    ),
    path("settings/categories/new", views.category_create, name="category_create"),
    path(
        "settings/categories/<int:cat_id>/delete",
        views.category_delete,
        name="category_delete",
    ),
    path("settings/account", views.settings_account, name="settings_account"),
    path("settings/data", views.settings_data, name="settings_data"),
    path("settings/data/export.json", views.settings_export_json, name="settings_export_json"),
    path(
        "settings/data/export/<str:table>.csv",
        views.settings_export_csv,
        name="settings_export_csv",
    ),
    path("settings/data/wipe", views.settings_wipe, name="settings_wipe"),
    path("settings/recurring", views.settings_recurring, name="settings_recurring"),
    path("settings/billing", views.settings_billing, name="settings_billing"),
    # Tools: Import
    path("import/", views.import_view, name="import_view"),
]
