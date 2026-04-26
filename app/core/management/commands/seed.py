"""Seed the default User + Profile + sample FxRate + default categories / targets.

Idempotent: safe to run repeatedly. Does not overwrite existing rows.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand

from core.models import (
    AllocationTarget,
    Category,
    EssentialsState,
    FxRate,
    Profile,
    TxType,
    User,
)

# Investment and Credit Card Payment are default-exempt.
DEFAULT_EXPENSE_CATEGORIES = [
    ("Housing & Rent", False),
    ("Food & Dining", False),
    ("Groceries", False),
    ("Transport", False),
    ("Healthcare", False),
    ("Education", False),
    ("Insurance", False),
    ("EMI & Loans", False),
    ("Entertainment", False),
    ("Utilities", False),
    ("Shopping", False),
    ("Investment", True),
    ("Travel & Vacations", False),
    ("Subscriptions", False),
    ("Personal Care", False),
    ("Transfers & Remittance", False),
    ("Credit Card Payment", True),
    ("Taxes", False),
    ("Cash Withdrawal", False),
    ("Childcare", False),
    ("Other Expense", False),
]

DEFAULT_INCOME_CATEGORIES = [
    "Salary",
    "Freelance",
    "Rental Income",
    "Dividend",
    "Interest",
    "Business",
    "Bonus",
    "Investment Proceeds",
    "Self Transfer",
    "Other Income",
]

# Default allocation: 55/20/10/10 to equity/debt/gold/alternatives, remaining 5% to Real Estate.
DEFAULT_ALLOCATION_PERCENTS = {
    "EQUITY": 55,
    "BONDS_DEBT": 20,
    "GOLD": 10,
    "ALTERNATIVES": 10,
    "REAL_ESTATE": 5,
}


class Command(BaseCommand):
    help = (
        "Create the default User, Profile, FxRate, categories, AllocationTarget, EssentialsState."
    )

    def handle(self, *args, **options):
        user = self._seed_user()
        profile = self._seed_profile(user)
        self._seed_fx(user)
        self._seed_categories(profile)
        self._seed_allocation(profile)
        self._seed_essentials(profile)
        self.stdout.write(self.style.SUCCESS("Seed complete."))

    def _seed_user(self) -> User:
        user, created = User.objects.get_or_create(
            username="self",
            defaults={"base_currency": "INR", "theme": "light"},
        )
        self._report("User", user.username, created)
        return user

    def _seed_profile(self, user: User) -> Profile:
        profile, created = Profile.objects.get_or_create(
            user=user, name="Self", defaults={"is_default": True}
        )
        self._report("Profile", profile.name, created)
        return profile

    def _seed_fx(self, user: User) -> None:
        fx, created = FxRate.objects.get_or_create(
            user=user,
            from_ccy="USD",
            to_ccy="INR",
            defaults={"rate": Decimal("83.0000")},
        )
        self._report("FxRate", f"{fx.from_ccy}->{fx.to_ccy}@{fx.rate}", created)

    def _seed_categories(self, profile: Profile) -> None:
        created_count = 0
        for name, is_exempt in DEFAULT_EXPENSE_CATEGORIES:
            _, created = Category.objects.get_or_create(
                profile=profile,
                type=TxType.EXPENSE,
                name=name,
                defaults={"is_exempt": is_exempt, "is_custom": False},
            )
            created_count += int(created)
        for name in DEFAULT_INCOME_CATEGORIES:
            _, created = Category.objects.get_or_create(
                profile=profile,
                type=TxType.INCOME,
                name=name,
                defaults={"is_exempt": False, "is_custom": False},
            )
            created_count += int(created)
        total = len(DEFAULT_EXPENSE_CATEGORIES) + len(DEFAULT_INCOME_CATEGORIES)
        self.stdout.write(f"  Categories: {created_count} created, {total - created_count} exist")

    def _seed_allocation(self, profile: Profile) -> None:
        target, created = AllocationTarget.objects.get_or_create(
            profile=profile,
            preset_name="Default",
            defaults={"percent_by_class": DEFAULT_ALLOCATION_PERCENTS},
        )
        self._report("AllocationTarget", target.preset_name, created)

    def _seed_essentials(self, profile: Profile) -> None:
        essentials, created = EssentialsState.objects.get_or_create(
            profile=profile,
            defaults={
                "emergency_fund_target_months": 6,
                "term_cover_target_multiplier": 10,
                "health_cover_target": Decimal("1000000"),
            },
        )
        self._report(
            "EssentialsState", f"emergency={essentials.emergency_fund_target_months}mo", created
        )

    def _report(self, kind: str, name: str, created: bool) -> None:
        prefix = "created" if created else "exists"
        self.stdout.write(f"  {prefix:>8} {kind}: {name}")
