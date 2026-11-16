from django.db import transaction


@transaction.atomic
def lock_account_owners(*owners) -> None:
    if not owners:
        return
    owner_model = type(owners[0])
    if any(type(owner) is not owner_model or owner.pk is None for owner in owners):
        raise ValueError("Account owners must be saved instances of the same model.")

    owner_ids = sorted({owner.pk for owner in owners})
    locked_ids = list(
        owner_model.objects.select_for_update()
        .filter(pk__in=owner_ids)
        .order_by("pk")
        .values_list("pk", flat=True)
    )
    if len(locked_ids) != len(owner_ids):
        raise owner_model.DoesNotExist("An account owner no longer exists.")
