"""Asset subtype registry.

Source: FEATURES.md §3.2. Each subtype key is stored on `Asset.subtype` (free-form string).
The registry drives:
- the subtype select on the asset form, filtered by category,
- the human-readable label on list pages,
- the "groups of relevant fields" hint that the form template uses to nudge which optional
  fields to show prominently. The hint is advisory only; all fields accept blank values.
"""

from __future__ import annotations

from core.models import AssetCategory

# Field-group hints. An asset template can use these to highlight relevant fields.
G_HOLDINGS = "holdings"  # quantity, unit_price, instrument_symbol, live_price_enabled
G_MATURITY = "maturity"  # start_date, maturity_date, interest_rate
G_PHYSICAL = "physical"  # quantity (grams), sub_class (purity)
G_PROPERTY = "property"  # sub_class (property type), notes (location)
G_BANK = "bank"  # notes (bank name)


ASSET_SUBTYPES: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {
    AssetCategory.EQUITY: [
        ("DIRECT_STOCK", "Direct Stock", (G_HOLDINGS,)),
        ("EQUITY_MF", "Equity Mutual Fund", (G_HOLDINGS,)),
        ("EMPLOYER_STOCK", "Employer Stock / ESOP", (G_HOLDINGS,)),
        ("ETF", "ETF", (G_HOLDINGS,)),
    ],
    AssetCategory.GOLD: [
        ("PHYSICAL_GOLD", "Physical Gold", (G_PHYSICAL,)),
        ("DIGITAL_GOLD", "Digital Gold", (G_PHYSICAL,)),
        ("SGB", "Sovereign Gold Bond", (G_HOLDINGS, G_MATURITY)),
        ("GOLD_ETF", "Gold ETF", (G_HOLDINGS,)),
        ("SILVER", "Silver", (G_PHYSICAL,)),
    ],
    AssetCategory.BONDS_DEBT: [
        ("BOND", "Bond", (G_MATURITY,)),
        ("DEBENTURE", "Debenture", (G_MATURITY,)),
        ("DEBT_MF", "Debt Mutual Fund", (G_HOLDINGS,)),
        ("CORPORATE_FD", "Corporate FD", (G_MATURITY,)),
        ("GOVT_SECURITY", "Govt Security", (G_MATURITY,)),
    ],
    AssetCategory.REAL_ESTATE: [
        ("RESIDENTIAL", "Residential Property", (G_PROPERTY,)),
        ("COMMERCIAL", "Commercial Property", (G_PROPERTY,)),
        ("LAND", "Land", (G_PROPERTY,)),
        ("REIT", "REIT", (G_HOLDINGS,)),
    ],
    AssetCategory.RETIREMENT: [
        ("EPF", "EPF", (G_MATURITY,)),
        ("PPF", "PPF", (G_MATURITY,)),
        ("NPS", "NPS", (G_MATURITY,)),
        ("SSY", "Sukanya Samriddhi", (G_MATURITY,)),
    ],
    AssetCategory.CASH: [
        ("SAVINGS", "Savings Account", (G_BANK,)),
        ("FD", "Fixed Deposit", (G_MATURITY,)),
        ("RD", "Recurring Deposit", (G_MATURITY,)),
        ("LIQUID_FUND", "Liquid Fund", (G_HOLDINGS,)),
        ("ARBITRAGE", "Arbitrage Fund", (G_HOLDINGS,)),
    ],
    AssetCategory.ALTERNATIVES: [
        ("P2P", "P2P Lending", (G_MATURITY,)),
        ("PMS_AIF", "PMS / AIF", (G_MATURITY,)),
    ],
    AssetCategory.OTHER: [
        ("OTHER", "Other", ()),
    ],
}

# Flat lookup: subtype key -> (category_key, label)
SUBTYPE_INDEX: dict[str, tuple[str, str]] = {
    key: (cat_key, label) for cat_key, items in ASSET_SUBTYPES.items() for key, label, _ in items
}


def subtypes_for(category: str) -> list[tuple[str, str]]:
    return [(key, label) for key, label, _ in ASSET_SUBTYPES.get(category, [])]


def label_for(subtype: str) -> str:
    entry = SUBTYPE_INDEX.get(subtype)
    return entry[1] if entry else subtype


def category_for(subtype: str) -> str | None:
    entry = SUBTYPE_INDEX.get(subtype)
    return entry[0] if entry else None


def category_label(category: str) -> str:
    return dict(AssetCategory.choices).get(category, category)


def category_hint(category: str) -> str:
    items = ASSET_SUBTYPES.get(category, [])
    return " \u00b7 ".join(label for _, label, _ in items[:5])


def all_categories() -> list[tuple[str, str, str]]:
    """Return list of (key, label, hint) for each asset category, in display order."""
    return [(cat, category_label(cat), category_hint(cat)) for cat in ASSET_SUBTYPES]
