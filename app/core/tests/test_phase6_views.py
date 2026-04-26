import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from core.models import Asset, Category, Profile, TxType, User


@pytest.fixture
def seeded(db):
    user = User.objects.create(username="self", base_currency="INR")
    profile = Profile.objects.create(user=user, name="Self", is_default=True)
    Category.objects.create(type=TxType.EXPENSE, name="Food")
    return profile


# ---- Import view ----------------------------------------------------------


@pytest.mark.django_db
def test_import_view_get_renders_assets_tab(seeded):
    resp = Client().get("/import/")
    assert resp.status_code == 200
    assert b"Import" in resp.content
    assert b"Append" in resp.content


@pytest.mark.django_db
def test_import_view_get_transactions_scope(seeded):
    resp = Client().get("/import/?scope=transactions")
    assert resp.status_code == 200
    assert b"date, type, category" in resp.content


@pytest.mark.django_db
def test_import_view_post_csv_creates_assets(seeded):
    csv_content = (
        b"name,category,subtype,currency,current_value\nINFY,EQUITY,DIRECT_STOCK,INR,500000\n"
    )
    upload = SimpleUploadedFile("assets.csv", csv_content, content_type="text/csv")
    resp = Client().post("/import/?scope=assets", {"mode": "append", "file": upload})
    assert resp.status_code == 302
    assert Asset.objects.filter(profile=seeded, name="INFY").exists()


@pytest.mark.django_db
def test_import_view_post_without_file_shows_error(seeded):
    resp = Client().post("/import/?scope=assets", {"mode": "append"})
    # Form invalid -> re-render at 200 with message.
    assert resp.status_code == 200


# ---- Settings: Account ----------------------------------------------------


@pytest.mark.django_db
def test_settings_account_get(seeded):
    resp = Client().get("/settings/account")
    assert resp.status_code == 200
    assert b"Profile" in resp.content
    assert b"App Lock" in resp.content


@pytest.mark.django_db
def test_settings_account_save_profile(seeded):
    resp = Client().post(
        "/settings/account",
        {
            "action": "save_profile",
            "first_name": "Demo",
            "last_name": "User",
            "email": "demo@example.com",
            "theme": "dark",
        },
    )
    assert resp.status_code == 302
    user = User.objects.get(username="self")
    assert user.first_name == "Demo"
    assert user.theme == "dark"


@pytest.mark.django_db
def test_settings_account_change_password(seeded):
    resp = Client().post(
        "/settings/account",
        {
            "action": "change_password",
            "new_password": "hunter22secure",
            "confirm_password": "hunter22secure",
        },
    )
    assert resp.status_code == 302
    user = User.objects.get(username="self")
    assert user.check_password("hunter22secure")


@pytest.mark.django_db
def test_settings_account_password_mismatch(seeded):
    resp = Client().post(
        "/settings/account",
        {
            "action": "change_password",
            "new_password": "hunter22secure",
            "confirm_password": "different12345",
        },
    )
    assert resp.status_code == 200
    assert b"do not match" in resp.content


# ---- Settings: Data + exports --------------------------------------------


@pytest.mark.django_db
def test_settings_data_page_renders(seeded):
    resp = Client().get("/settings/data")
    assert resp.status_code == 200
    assert b"Export everything" in resp.content
    assert b"Danger zone" in resp.content


@pytest.mark.django_db
def test_settings_export_json_downloads(seeded):
    resp = Client().get("/settings/data/export.json")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "application/json"
    assert "attachment" in resp["Content-Disposition"]
    payload = json.loads(resp.content.decode("utf-8"))
    assert payload["profile"]["name"] == "Self"


@pytest.mark.django_db
def test_settings_export_csv_assets(seeded):
    Asset.objects.create(
        profile=seeded,
        category="EQUITY",
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value="1000",
    )
    resp = Client().get("/settings/data/export/assets.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"] == "text/csv"
    assert b"INFY" in resp.content


@pytest.mark.django_db
def test_settings_export_csv_unknown_table_404(seeded):
    resp = Client().get("/settings/data/export/mystery.csv")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_settings_wipe_requires_confirm_keyword(seeded):
    Asset.objects.create(
        profile=seeded,
        category="EQUITY",
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value="1000",
    )
    resp = Client().post("/settings/data/wipe", {"confirm": "maybe"})
    assert resp.status_code == 302
    assert Asset.objects.filter(profile=seeded).exists()


@pytest.mark.django_db
def test_settings_wipe_happy_path(seeded):
    Asset.objects.create(
        profile=seeded,
        category="EQUITY",
        subtype="DIRECT_STOCK",
        name="INFY",
        currency="INR",
        current_value="1000",
    )
    resp = Client().post("/settings/data/wipe", {"confirm": "WIPE"})
    assert resp.status_code == 302
    assert not Asset.objects.filter(profile=seeded).exists()


# ---- Settings: Recurring + Billing ---------------------------------------


@pytest.mark.django_db
def test_settings_recurring_empty(seeded):
    resp = Client().get("/settings/recurring")
    assert resp.status_code == 200
    assert b"No recurring rules" in resp.content


@pytest.mark.django_db
def test_settings_billing_renders(seeded):
    resp = Client().get("/settings/billing")
    assert resp.status_code == 200
    assert b"Free forever" in resp.content
