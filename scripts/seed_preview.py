"""Seed local-only demo accounts for the UI preview database."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mk.settings")

import django

django.setup()

from accounts.models import User
from catalog.models import Category, Listing, VendorProfile
from ledger.models import Account, LedgerEntry


def user(username, password, **flags):
    obj, _ = User.objects.update_or_create(username=username, defaults=flags)
    obj.set_password(password)
    obj.save(update_fields=("password",))
    return obj


def account(owner, kind, amount, ref):
    obj, _ = Account.objects.get_or_create(owner=owner, kind=kind)
    if not obj.entries.filter(ref=ref).exists():
        LedgerEntry.objects.create(account=obj, amount=amount, ref=ref)
    return obj


admin = user("demo_admin", "KolaDemoAdmin!2026", is_staff=True, is_superuser=True)
customer = user("demo_customer", "KolaDemoCustomer!2026")
vendor = user("demo_vendor", "KolaDemoVendor!2026")

account(customer, Account.Kind.USER_AVAILABLE, 125_000_000, "preview-customer-funding")
account(vendor, Account.Kind.VENDOR_AVAILABLE, 480_000_000, "preview-vendor-funding")
bond = account(vendor, Account.Kind.VENDOR_BOND, 250_000_000, "preview-vendor-bond")

profile, _ = VendorProfile.objects.update_or_create(
    user=vendor,
    defaults={"bond_account": bond, "is_approved": True},
)
category, _ = Category.objects.get_or_create(name="Preview goods", slug="preview-goods")
Listing.objects.update_or_create(
    vendor=profile,
    category=category,
    title="Demo listing for UI review",
    defaults={
        "description": "A local-only listing used to inspect the marketplace interface.",
        "price": 35_000_000,
        "stock": 12,
        "is_active": True,
        "is_approved": True,
        "shipping_required": False,
    },
)

print("Seeded demo_admin, demo_customer, and demo_vendor")
