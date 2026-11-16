from django.contrib.auth import get_user_model
from django.db import transaction

from catalog.models import VendorProfile
from ledger.models import Account


@transaction.atomic
def create_vendor_profile(user) -> VendorProfile:
    locked_user = get_user_model().objects.select_for_update().get(pk=user.pk)
    profile = VendorProfile.objects.filter(user=locked_user).first()
    if profile is not None:
        return profile

    bond_account = Account.objects.create(
        kind=Account.Kind.VENDOR_BOND,
        owner=locked_user,
    )
    return VendorProfile.objects.create(
        user=locked_user,
        bond_account=bond_account,
    )
