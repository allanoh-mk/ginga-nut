import pytest
from django.urls import reverse

from accounts.models import User
from catalog.models import Category, Listing, Review
from core.services.create_vendor_profile import create_vendor_profile
from orders.models import Order


@pytest.fixture
def finalized_order(db):
    buyer = User.objects.create_user(username="review-buyer")
    vendor_user = User.objects.create_user(username="review-vendor")
    vendor = create_vendor_profile(vendor_user)
    vendor.is_approved = True
    vendor.save(update_fields=("is_approved",))
    category = Category.objects.create(name="Review goods", slug="review-goods")
    listing = Listing.objects.create(
        vendor=vendor,
        category=category,
        title="Reviewed item",
        description="A product with reviews.",
        price=100_000_000,
        stock=1,
        is_active=True,
    )
    order = Order.objects.create(
        buyer=buyer,
        vendor=vendor,
        listing=listing,
        listing_title=listing.title,
        quantity=1,
        unit_price=listing.price,
        total_amount=listing.price,
        state=Order.State.FINALIZED,
    )
    return buyer, vendor_user, listing, order


@pytest.mark.django_db
def test_buyer_review_updates_listing_rating_and_is_single_use(
    client,
    finalized_order,
):
    buyer, _, listing, order = finalized_order
    client.force_login(buyer)
    url = reverse("orders:submit-review", args=(order.pk,))

    response = client.post(url, {"rating": "5", "comment": "Excellent item"})

    assert response.status_code == 302
    review = Review.objects.get(order=order)
    assert review.rating == 5
    assert review.comment == "Excellent item"
    listing.refresh_from_db()
    assert listing.average_rating == 5
    assert listing.review_count == 1
    assert (
        client.get(reverse("catalog:listing-reviews", args=(listing.pk,))).status_code
        == 200
    )

    duplicate = client.post(url, {"rating": "4", "comment": "Second attempt"})
    assert duplicate.status_code == 400
    assert Review.objects.filter(order=order).count() == 1


@pytest.mark.django_db
def test_non_buyer_cannot_review_order(client, finalized_order):
    _, vendor_user, _, order = finalized_order
    client.force_login(vendor_user)

    response = client.post(
        reverse("orders:submit-review", args=(order.pk,)),
        {"rating": "5", "comment": ""},
    )

    assert response.status_code == 403
    assert not Review.objects.filter(order=order).exists()


@pytest.mark.django_db
def test_unfinalized_order_cannot_be_reviewed(finalized_order):
    from django.core.exceptions import ValidationError

    from core.services.submit_review import submit_review

    buyer, _, _, order = finalized_order
    order.state = Order.State.DELIVERED
    order.save(update_fields=("state",))

    with pytest.raises(ValidationError, match="Only finalized orders"):
        submit_review(order.pk, buyer, 4)


@pytest.mark.django_db
def test_deleting_review_recomputes_listing_aggregates(finalized_order):
    _, _, listing, order = finalized_order
    Review.objects.create(order=order, rating=3, comment="Okay")
    listing.refresh_from_db()
    assert listing.average_rating == 3
    assert listing.review_count == 1

    Review.objects.get(order=order).delete()

    listing.refresh_from_db()
    assert listing.average_rating == 0
    assert listing.review_count == 0
