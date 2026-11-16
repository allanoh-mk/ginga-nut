from django.db import transaction
from django.db.models import Avg, Count
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from catalog.models import Listing, Review


def _update_listing_review_stats(listing_id: int) -> None:
    with transaction.atomic():
        Listing.objects.select_for_update().get(pk=listing_id)
        stats = Review.objects.filter(order__listing_id=listing_id).aggregate(
            average=Avg("rating"),
            count=Count("pk"),
        )
        Listing.objects.filter(pk=listing_id).update(
            average_rating=stats["average"] or 0,
            review_count=stats["count"],
        )


@receiver(post_save, sender=Review)
def update_listing_review_stats_on_save(sender, instance, **kwargs) -> None:
    _update_listing_review_stats(instance.order.listing_id)


@receiver(post_delete, sender=Review)
def update_listing_review_stats_on_delete(sender, instance, **kwargs) -> None:
    _update_listing_review_stats(instance.order.listing_id)
