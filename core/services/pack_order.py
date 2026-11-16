from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.services.order_transitions import apply_order_transition
from orders.models import Order
from orders.uploads import strip_image_metadata


@transaction.atomic
def pack_order(order_id: int, actor, photo) -> Order:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("vendor__user")
        .get(pk=order_id)
    )
    if order.vendor_id is None or order.vendor.user_id != actor.pk:
        raise PermissionDenied("Only the order's vendor can pack it.")
    apply_order_transition(order, "pack", actor=actor)
    if photo is None:
        raise ValidationError("A pack photo is required.")

    field = Order._meta.get_field("pack_photo")
    order.pack_photo = field.clean(strip_image_metadata(photo), order)
    order.save(update_fields=("pack_photo", "state", "updated_at"))
    return order
