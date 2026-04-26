"""Django ModelForms for Asset / Liability / Transaction / Category CRUD.

Tag handling: Asset and Liability forms expose a free-form `tags_raw` CharField.
Views convert that via `core.services.tags.parse_tags`. On edit, `__init__`
pre-populates `tags_raw` from the instance.

Transactions use a plain `Form` per row inside a formset so the add page supports
spreadsheet-style multi-row entry (see TransactionRowForm + transaction_formset).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from django import forms
from django.forms import formset_factory

from core.models import Asset, Category, EssentialsState, Goal, Liability, Transaction, TxType, User
from core.services.tags import serialize_tags
from core.subtypes import SUBTYPE_INDEX

CURRENCY_CHOICES = [
    ("INR", "INR"),
    ("USD", "USD"),
    ("EUR", "EUR"),
    ("GBP", "GBP"),
    ("SGD", "SGD"),
    ("AED", "AED"),
]

INPUT_CSS = "w-full rounded border border-slate-300 px-3 py-2 text-sm"


class AssetForm(forms.ModelForm):
    tags_raw = forms.CharField(
        required=False,
        label="Tags",
        help_text="Comma-separated, e.g. tax-saving, long-term",
        widget=forms.TextInput(attrs={"placeholder": "tax-saving, long-term"}),
    )

    class Meta:
        model = Asset
        fields = [
            "category",
            "subtype",
            "name",
            "currency",
            "current_value",
            "cost_basis",
            "quantity",
            "unit_price",
            "instrument_symbol",
            "live_price_enabled",
            "sub_class",
            "start_date",
            "maturity_date",
            "interest_rate",
            "geography",
            "weight",
            "notes",
            "exclude_from_allocation",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "maturity_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["tags_raw"] = serialize_tags(self.instance.tags.all())
        for name, field in self.fields.items():
            if name == "live_price_enabled" or name == "exclude_from_allocation":
                continue
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (
                css + " w-full rounded border border-slate-300 px-3 py-2 text-sm"
            ).strip()

    def clean_subtype(self) -> str:
        subtype = (self.cleaned_data.get("subtype") or "").strip()
        if not subtype:
            raise forms.ValidationError("Pick a subtype.")
        if subtype not in SUBTYPE_INDEX:
            raise forms.ValidationError("Unknown subtype.")
        category = self.cleaned_data.get("category")
        if category and SUBTYPE_INDEX[subtype][0] != category:
            raise forms.ValidationError("Subtype doesn't match the chosen category.")
        return subtype


class LiabilityForm(forms.ModelForm):
    tags_raw = forms.CharField(
        required=False,
        label="Tags",
        help_text="Comma-separated",
        widget=forms.TextInput(attrs={"placeholder": "e.g. secured, long-term"}),
    )

    class Meta:
        model = Liability
        fields = [
            "category",
            "name",
            "currency",
            "outstanding_amount",
            "interest_rate",
            "monthly_emi",
            "start_date",
            "notes",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial["tags_raw"] = serialize_tags(self.instance.tags.all())
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " " + INPUT_CSS).strip()


class TransactionRowForm(forms.Form):
    """One row of the multi-row add form.

    `category` choices depend on the active profile and tx_type, so the view passes
    them in via `form_kwargs` to the formset.
    """

    date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": INPUT_CSS}),
        initial=date_type.today,
    )
    category = forms.TypedChoiceField(
        coerce=int, choices=[], widget=forms.Select(attrs={"class": INPUT_CSS})
    )
    description = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "e.g. Rent"}),
    )
    amount = forms.DecimalField(
        max_digits=20,
        decimal_places=4,
        min_value=Decimal("0.0001"),
        widget=forms.NumberInput(attrs={"class": INPUT_CSS, "placeholder": "0", "step": "0.01"}),
    )
    currency = forms.ChoiceField(
        choices=CURRENCY_CHOICES,
        initial="INR",
        widget=forms.Select(attrs={"class": INPUT_CSS}),
    )
    is_recurring = forms.BooleanField(required=False)
    tags_raw = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "tags"})
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "optional note"}),
    )

    def __init__(self, *args, categories: list[tuple[int, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].choices = categories or []


TransactionFormSet = formset_factory(TransactionRowForm, extra=1, can_delete=False)


class TransactionEditForm(forms.ModelForm):
    """Single-row edit form. Similar to Asset/Liability forms but for Transaction."""

    tags_raw = forms.CharField(required=False, label="Tags")
    is_recurring = forms.BooleanField(required=False, label="Mark as Recurring")

    class Meta:
        model = Transaction
        fields = ["date", "category", "description", "amount", "currency", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, categories: list[tuple[int, str]] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        if categories is not None:
            self.fields["category"].queryset = Category.objects.filter(
                id__in=[c for c, _ in categories]
            )
        if self.instance and self.instance.pk:
            self.initial["tags_raw"] = serialize_tags(self.instance.tags.all())
            self.initial["is_recurring"] = self.instance.recurring_rule_id is not None
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " " + INPUT_CSS).strip()


class GoalForm(forms.ModelForm):
    """Goal CRUD. `linked_asset_ids_raw` is a comma-separated asset ID list (optional)."""

    linked_asset_ids_raw = forms.CharField(
        required=False,
        label="Link specific assets (optional)",
        help_text="Comma-separated asset IDs. Leave blank to track the whole class.",
    )

    class Meta:
        model = Goal
        fields = [
            "name",
            "template_id",
            "target_amount",
            "currency",
            "target_date",
            "linked_asset_class",
        ]
        widgets = {
            "target_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, track_choices=None, template_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if template_choices is not None:
            self.fields["template_id"] = forms.ChoiceField(
                required=False, choices=template_choices, label="Template"
            )
        if track_choices is not None:
            self.fields["linked_asset_class"] = forms.ChoiceField(
                choices=track_choices, label="Track Progress By"
            )
        self.fields["currency"] = forms.ChoiceField(choices=CURRENCY_CHOICES, initial="INR")
        if self.instance and self.instance.pk and self.instance.linked_asset_ids:
            self.initial["linked_asset_ids_raw"] = ", ".join(
                str(i) for i in self.instance.linked_asset_ids
            )
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " " + INPUT_CSS).strip()

    def clean_linked_asset_ids_raw(self) -> list[int]:
        raw = (self.cleaned_data.get("linked_asset_ids_raw") or "").strip()
        if not raw:
            return []
        ids: list[int] = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.append(int(chunk))
            except ValueError as exc:
                raise forms.ValidationError(f"Invalid asset id: {chunk}") from exc
        return ids


class EssentialsForm(forms.ModelForm):
    class Meta:
        model = EssentialsState
        fields = [
            "emergency_fund_target_months",
            "term_cover_amount",
            "term_cover_target_multiplier",
            "health_cover_amount",
            "health_cover_target",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            css = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = (css + " " + INPUT_CSS).strip()


class CategoryForm(forms.Form):
    type = forms.ChoiceField(
        choices=TxType.choices, widget=forms.Select(attrs={"class": INPUT_CSS})
    )
    name = forms.CharField(
        max_length=80,
        widget=forms.TextInput(attrs={"class": INPUT_CSS, "placeholder": "Category name"}),
    )
    is_exempt = forms.BooleanField(required=False, label="Exclude from totals")


class AccountForm(forms.ModelForm):
    """Account profile fields: display name + theme preference."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "theme"]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "last_name": forms.TextInput(attrs={"class": INPUT_CSS}),
            "email": forms.EmailInput(attrs={"class": INPUT_CSS}),
            "theme": forms.Select(attrs={"class": INPUT_CSS}),
        }


class PasswordChangeForm(forms.Form):
    """Local password change. Single-user app; we don't require the old password."""

    new_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": INPUT_CSS, "autocomplete": "new-password"}),
        label="New password",
    )
    confirm_password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": INPUT_CSS, "autocomplete": "new-password"}),
        label="Confirm",
    )

    def clean(self) -> dict:
        cleaned = super().clean()
        if cleaned.get("new_password") != cleaned.get("confirm_password"):
            raise forms.ValidationError("Passwords do not match.")
        return cleaned


class ImportUploadForm(forms.Form):
    file = forms.FileField(
        label="CSV file",
        widget=forms.FileInput(attrs={"accept": ".csv,text/csv", "class": "text-sm"}),
    )


class _MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class _MultipleFileField(forms.FileField):
    """FileField that accepts and validates a list of files.

    ``cleaned_data`` is always a list (possibly empty) so callers do not
    need to branch on single-vs-list. Mirrors the canonical pattern from
    the Django docs.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", _MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if data in (None, "", []):
            return []
        if isinstance(data, list | tuple):
            return [single(d, initial) for d in data if d]
        return [single(data, initial)]


class BrokerImportForm(forms.Form):
    """Upload form for broker-native statements (Zerodha XLSX / Chola PDF /
    Aionion XLSX).

    The demat account is identified by the broker-issued **client ID**
    embedded in the file's preamble (Aionion ``CLIENT ID`` cell, Zerodha
    ``Client ID`` cell, Chola customer-name line). The view sniffs that
    value at upload time and uses it as the BrokerAccount label. Files
    that do not carry a recognisable client ID are rejected.

    Both file fields accept multiple files so a user can upload several
    periods at once (e.g. three years of Aionion equity-trade exports).
    Both are optional so the user can upload whichever they have this
    month (Zerodha ships tradebook + dividends separately).
    """

    BROKER_CHOICES = [
        ("zerodha", "Zerodha"),
        ("chola", "Cholamandalam Securities"),
        ("aionion", "Aionion"),
    ]

    broker = forms.ChoiceField(choices=BROKER_CHOICES)
    tradebook = _MultipleFileField(
        required=False,
        label="Tradebook / statement file(s)",
        help_text="Zerodha tradebook XLSX, Aionion equity-trades XLSX, or Chola TransactionReport PDF. Multiple files allowed.",
        widget=_MultipleFileInput(attrs={"accept": ".xlsx,.pdf", "class": "text-sm", "multiple": True}),
    )
    dividends = _MultipleFileField(
        required=False,
        label="Dividends file(s)",
        help_text=(
            "Zerodha or Aionion dividends XLSX. Multiple files allowed. "
            "Leave blank for Chola -- dividends live in the same PDF."
        ),
        widget=_MultipleFileInput(attrs={"accept": ".xlsx", "class": "text-sm", "multiple": True}),
    )

    def clean(self):
        data = super().clean()
        if not data.get("tradebook") and not data.get("dividends"):
            raise forms.ValidationError(
                "Upload at least one file (tradebook or dividends)."
            )
        return data
