from django.core.exceptions import PermissionDenied
from django.db import transaction

from catalog.models import VendorProfile
from core.services.notify import notify_user


@transaction.atomic
def approve_vendor(profile_id: int, *, actor) -> VendorProfile:
    if not actor.is_authenticated or not actor.is_staff:
        raise PermissionDenied("Only an admin can approve vendors.")

    profile = VendorProfile.objects.select_for_update().get(pk=profile_id)
    profile.is_approved = True
    profile.save(update_fields=("is_approved",))
    notify_user(
        profile.user,
        "vendor_approved",
        "Your vendor profile has been approved.",
        {"vendor_profile_id": profile.pk},
        actor=actor,
    )
    return profile
