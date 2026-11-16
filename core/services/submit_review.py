from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from catalog.models import Listing, Review
from orders.models import Order


@transaction.atomic
def submit_review(order_id: int, actor, rating: int, comment: str = "") -> Review:
    order = (
        Order.objects.select_for_update(of=("self",))
        .select_related("buyer", "listing")
        .get(pk=order_id)
    )
    if actor is None or not actor.is_authenticated or order.buyer_id != actor.pk:
        raise PermissionDenied("Only the order's buyer can submit a review.")
    if order.state != Order.State.FINALIZED:
        raise ValidationError("Only finalized orders can be reviewed.")
    Listing.objects.select_for_update().get(pk=order.listing_id)
    if Review.objects.filter(order=order).exists():
        raise ValidationError("This order has already been reviewed.")
    if (
        isinstance(rating, bool)
        or not isinstance(rating, int)
        or rating not in range(1, 6)
    ):
        raise ValidationError("Rating must be from 1 to 5.")
    if not isinstance(comment, str) or len(comment) > 2000:
        raise ValidationError("Review comments must be 2,000 characters or fewer.")

    review = Review(order=order, rating=rating, comment=comment.strip())
    review.full_clean()
    review.save()
    return review
