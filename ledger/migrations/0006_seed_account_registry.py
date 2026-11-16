from django.db import migrations

ACCOUNT_KINDS = (
    "external",
    "user_available",
    "user_escrow",
    "vendor_available",
    "vendor_bond",
    "market_fee",
    "market_spread",
    "treasury",
    "suspense",
)


def seed_account_registry(apps, schema_editor):
    Account = apps.get_model("ledger", "Account")
    VendorProfile = apps.get_model("catalog", "VendorProfile")
    database = schema_editor.connection.alias

    for profile in (
        VendorProfile.objects.using(database).select_related("bond_account").iterator()
    ):
        account = profile.bond_account
        if account.owner_id is None:
            account.owner_id = profile.user_id
            account.save(using=database, update_fields=("owner",))
        elif account.owner_id != profile.user_id:
            raise RuntimeError(
                f"Vendor profile {profile.pk} has a bond account owned by another user."
            )

    for kind in ACCOUNT_KINDS:
        if (
            not Account.objects.using(database)
            .filter(
                kind=kind,
                owner__isnull=True,
            )
            .exists()
        ):
            Account.objects.using(database).create(kind=kind)


class Migration(migrations.Migration):
    dependencies = [
        ("ledger", "0005_alter_account_kind"),
        ("catalog", "0003_remove_vendorprofile_bond_amount_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_account_registry, migrations.RunPython.noop),
    ]
