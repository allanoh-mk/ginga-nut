from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connections
from django.urls import reverse

from accounts.models import User
from catalog.exceptions import InsufficientStock, ListingUnavailable
from catalog.models import Category, Listing, VendorProfile
from core.services.approve_vendor import approve_vendor
from core.services.create_order import create_order
from core.services.create_vendor_profile import create_vendor_profile
from core.services.decrement_stock import decrement_stock
from core.services.save_listing import save_listing
from ledger.models import Account
from orders.models import City, DeliveryZone, Order


@pytest.fixture
def checkout_encryption_key(settings) -> None:
    settings.FIELD_ENCRYPTION_KEY = Fernet.generate_key().decode()


@pytest.fixture
def category(db) -> Category:
    return Category.objects.create(name="Books", slug="books")


@pytest.fixture
def buyer(db) -> User:
    return User.objects.create_user(username="catalog_buyer", password="unused")


@pytest.fixture
def vendor(db) -> tuple[User, VendorProfile]:
    user = User.objects.create_user(username="catalog_vendor", password="unused")
    return user, create_vendor_profile(user)


@pytest.fixture
def approved_vendor(db, vendor) -> tuple[User, VendorProfile]:
    user, profile = vendor
    profile.is_approved = True
    profile.save(update_fields=("is_approved",))
    return user, profile


@pytest.fixture
def listing(db, category, approved_vendor) -> Listing:
    _, profile = approved_vendor
    return Listing.objects.create(
        vendor=profile,
        category=category,
        title="Field Guide",
        description="A useful guide.",
        price=123_456_789,
        stock=5,
        is_active=True,
    )


@pytest.mark.django_db
def test_unapproved_vendor_cannot_create_listing(vendor, category) -> None:
    user, _ = vendor

    with pytest.raises(PermissionDenied):
        save_listing(
            actor=user,
            listing_id=None,
            values={
                "category": category,
                "title": "Blocked listing",
                "description": "Not yet approved.",
                "price": 100,
                "stock": 1,
                "is_active": True,
            },
        )

    assert Listing.objects.count() == 0


@pytest.mark.django_db
def test_vendor_cannot_create_digital_listing(approved_vendor, category) -> None:
    user, _ = approved_vendor

    with pytest.raises(ValidationError, match="Digital listings are unavailable"):
        save_listing(
            actor=user,
            listing_id=None,
            values={
                "category": category,
                "title": "Digital listing",
                "description": "Fulfillment is not available.",
                "price": 100,
                "stock": 1,
                "is_active": True,
                "shipping_required": False,
            },
        )

    assert not Listing.objects.exists()


@pytest.mark.django_db
def test_public_pages_hide_unapproved_vendor_listings(client, category, vendor) -> None:
    _, profile = vendor
    listing = Listing.objects.create(
        vendor=profile,
        category=category,
        title="Pending product",
        description="Not public until approval.",
        price=100,
        stock=1,
        is_active=True,
    )

    response = client.get(reverse("catalog:category", args=[category.slug]))
    assert response.status_code == 200
    assert b"Pending product" not in response.content
    assert client.get(reverse("catalog:listing", args=[listing.pk])).status_code == 404


@pytest.mark.django_db
def test_admin_approval_queue_approves_vendor_and_enables_public_listing(
    client,
    category,
    vendor,
) -> None:
    admin = User.objects.create_superuser(
        username="catalog_admin",
        password="a-very-long-unique-password-8492",
    )
    _, profile = vendor
    listing = Listing.objects.create(
        vendor=profile,
        category=category,
        title="Approved product",
        description="Public after approval.",
        price=200,
        stock=3,
        is_active=True,
    )
    queue_url = reverse("catalog:vendor-approval-queue")
    approve_url = reverse("catalog:vendor-approve", args=[profile.pk])

    assert client.get(queue_url).status_code == 302
    client.force_login(admin)
    assert b"catalog_vendor" in client.get(queue_url).content

    response = client.post(approve_url)

    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.is_approved is True
    assert (
        b"Approved product"
        in client.get(reverse("catalog:category", args=[category.slug])).content
    )
    assert client.get(reverse("catalog:listing", args=[listing.pk])).status_code == 200


@pytest.mark.django_db
def test_non_admin_cannot_approve_vendor(vendor) -> None:
    user, profile = vendor

    with pytest.raises(PermissionDenied):
        approve_vendor(profile.pk, actor=user)

    profile.refresh_from_db()
    assert profile.is_approved is False


@pytest.mark.django_db
def test_vendor_crud_creates_updates_and_deletes_listing(
    client,
    approved_vendor,
    category,
) -> None:
    user, _ = approved_vendor
    client.force_login(user)
    create_url = reverse("catalog:vendor-create-listing")
    response = client.post(
        create_url,
        {
            "category": category.pk,
            "title": "Notebook",
            "description": "Plain paper notebook.",
            "price": "250000000",
            "stock": "12",
            "is_active": "on",
        },
    )

    assert response.status_code == 302
    listing = Listing.objects.get(title="Notebook")
    assert listing.price == 250_000_000
    assert listing.stock == 12
    assert listing.is_active is True

    response = client.post(
        reverse("catalog:vendor-edit-listing", args=[listing.pk]),
        {
            "category": category.pk,
            "title": "Updated notebook",
            "description": "Recycled paper notebook.",
            "price": "300000000",
            "stock": "8",
            "is_active": "",
        },
    )
    assert response.status_code == 302
    listing.refresh_from_db()
    assert listing.title == "Updated notebook"
    assert listing.stock == 8
    assert listing.is_active is False

    response = client.post(reverse("catalog:vendor-delete-listing", args=[listing.pk]))
    assert response.status_code == 302
    assert not Listing.objects.filter(pk=listing.pk).exists()


@pytest.mark.django_db
def test_vendor_application_creates_pending_profile(client, buyer) -> None:
    client.force_login(buyer)

    response = client.post(reverse("catalog:vendor-dashboard"))

    assert response.status_code == 302
    profile = VendorProfile.objects.get(user=buyer)
    assert profile.is_approved is False
    assert profile.bond_amount == 0
    assert client.get(reverse("catalog:vendor-dashboard")).status_code == 200


@pytest.mark.django_db
def test_category_detail_paginates_listings(client, category, approved_vendor) -> None:
    _, profile = approved_vendor
    Listing.objects.bulk_create(
        [
            Listing(
                vendor=profile,
                category=category,
                title=f"Paged listing {index:02}",
                description="Pagination test listing.",
                price=100,
                stock=1,
                is_active=True,
            )
            for index in range(30)
        ]
    )

    first_page = client.get(reverse("catalog:category", args=[category.slug]))
    second_page = client.get(
        reverse("catalog:category", args=[category.slug]),
        {"page": 2},
    )

    assert first_page.status_code == 200
    assert len(first_page.context["listings"]) == 25
    assert b"Next" in first_page.content
    assert len(second_page.context["listings"]) == 5
    assert b"Previous" in second_page.content


@pytest.mark.django_db
def test_vendor_dashboard_paginates_own_listings(
    client,
    approved_vendor,
    category,
) -> None:
    user, profile = approved_vendor
    Listing.objects.bulk_create(
        [
            Listing(
                vendor=profile,
                category=category,
                title=f"Vendor listing {index:02}",
                description="Vendor pagination test listing.",
                price=100,
                stock=1,
                is_active=True,
            )
            for index in range(30)
        ]
    )
    client.force_login(user)

    first_page = client.get(reverse("catalog:vendor-dashboard"))
    second_page = client.get(reverse("catalog:vendor-dashboard"), {"page": 2})

    assert len(first_page.context["listings"]) == 25
    assert b"Next" in first_page.content
    assert len(second_page.context["listings"]) == 5
    assert b"Previous" in second_page.content


@pytest.mark.django_db
def test_vendor_approval_queue_paginates(client) -> None:
    admin = User.objects.create_superuser(username="pagination_admin")
    for index in range(30):
        user = User.objects.create_user(username=f"pending_vendor_{index}")
        bond_account = Account.objects.create(
            kind=Account.Kind.VENDOR_BOND,
            owner=user,
        )
        VendorProfile.objects.create(user=user, bond_account=bond_account)
    client.force_login(admin)

    first_page = client.get(reverse("catalog:vendor-approval-queue"))
    second_page = client.get(
        reverse("catalog:vendor-approval-queue"),
        {"page": 2},
    )

    assert len(first_page.context["profiles"]) == 25
    assert b"Next" in first_page.content
    assert len(second_page.context["profiles"]) == 5
    assert b"Previous" in second_page.content


@pytest.mark.django_db
def test_authenticated_buyer_can_checkout_and_reserve_stock(
    client,
    buyer,
    listing,
    checkout_encryption_key,
) -> None:
    client.force_login(buyer)
    checkout_url = reverse("catalog:checkout", args=[listing.pk])

    response = client.post(
        checkout_url,
        {
            "quantity": "2",
            "shipping_address": "12 Market Street",
            "shipping_phone": "+254700000000",
            "delivery_zone": "",
        },
    )

    assert response.status_code == 302
    order = Order.objects.get()
    assert response["Location"] == reverse("orders:detail", args=[order.pk])
    assert order.buyer == buyer
    assert order.vendor == listing.vendor
    assert order.listing == listing
    assert order.quantity == 2
    assert order.total_amount == listing.price * 2
    assert order.delivery_type == Order.DeliveryType.PHYSICAL
    assert order.shipping_address == "12 Market Street"
    assert order.shipping_phone == "+254700000000"
    confirmation = client.get(response["Location"])
    assert b"Order placed. Fund it to proceed." in confirmation.content
    assert Account.objects.filter(
        owner=buyer,
        kind=Account.Kind.USER_ESCROW,
    ).exists()
    listing.refresh_from_db()
    assert listing.stock == 3


@pytest.mark.django_db
def test_checkout_rejects_quantity_above_available_stock(
    client,
    buyer,
    listing,
    checkout_encryption_key,
) -> None:
    client.force_login(buyer)

    response = client.post(
        reverse("catalog:checkout", args=[listing.pk]),
        {
            "quantity": "6",
            "shipping_address": "12 Market Street",
            "shipping_phone": "+254700000000",
            "delivery_zone": "",
        },
    )

    assert response.status_code == 200
    assert b"Ensure this value is less than or equal to 5" in response.content
    assert not Order.objects.exists()
    listing.refresh_from_db()
    assert listing.stock == 5


@pytest.mark.django_db
def test_listing_buy_link_requires_authentication(client, buyer, listing) -> None:
    listing_url = reverse("catalog:listing", args=[listing.pk])
    checkout_url = reverse("catalog:checkout", args=[listing.pk])

    assert checkout_url.encode() not in client.get(listing_url).content
    client.force_login(buyer)
    assert checkout_url.encode() in client.get(listing_url).content


@pytest.mark.django_db
def test_digital_listing_is_not_public_or_orderable(
    client,
    buyer,
    listing,
    checkout_encryption_key,
) -> None:
    listing.shipping_required = False
    listing.save(update_fields=("shipping_required",))
    client.force_login(buyer)

    assert client.get(reverse("catalog:listing", args=[listing.pk])).status_code == 404
    response = client.post(
        reverse("catalog:checkout", args=[listing.pk]),
        {"quantity": "1"},
    )
    assert response.status_code == 404
    assert not Order.objects.exists()
    with pytest.raises(ValidationError, match="Digital listings are unavailable"):
        create_order(buyer=buyer, listing_id=listing.pk, quantity=1)
    assert not Order.objects.exists()
    listing.refresh_from_db()
    assert listing.stock == 5


@pytest.mark.django_db
def test_zone_restricted_checkout_requires_the_listing_zone(
    client,
    buyer,
    listing,
    checkout_encryption_key,
) -> None:
    city = City.objects.create(name="Checkout City", slug="checkout-city")
    allowed_zone = DeliveryZone.objects.create(city=city, name="Allowed")
    other_zone = DeliveryZone.objects.create(city=city, name="Other")
    listing.delivery_zone = allowed_zone
    listing.save(update_fields=("delivery_zone",))
    client.force_login(buyer)
    checkout_url = reverse("catalog:checkout", args=[listing.pk])
    form_data = {
        "quantity": "1",
        "shipping_address": "12 Market Street",
        "shipping_phone": "+254700000000",
    }

    invalid_response = client.post(
        checkout_url,
        {**form_data, "delivery_zone": other_zone.pk},
    )
    assert invalid_response.status_code == 200
    assert not Order.objects.exists()
    listing.refresh_from_db()
    assert listing.stock == 5

    valid_response = client.post(
        checkout_url,
        {**form_data, "delivery_zone": allowed_zone.pk},
    )
    assert valid_response.status_code == 302
    assert Order.objects.get().delivery_zone == allowed_zone


@pytest.mark.django_db
def test_vendor_profile_creation_is_idempotent(vendor) -> None:
    user, profile = vendor

    repeated = create_vendor_profile(user)

    assert repeated.pk == profile.pk
    assert repeated.bond_account_id == profile.bond_account_id
    assert repeated.bond_account.kind == "vendor_bond"


@pytest.mark.django_db
def test_vendor_bond_amount_is_aggregated_from_ledger(vendor) -> None:
    from ledger.models import Account, LedgerEntry

    _, profile = vendor
    treasury = Account.objects.create(kind=Account.Kind.TREASURY)
    LedgerEntry.objects.create(
        account=profile.bond_account,
        amount=500,
        ref="bond-funding",
    )
    LedgerEntry.objects.create(
        account=treasury,
        amount=-500,
        ref="bond-funding",
    )

    profile.refresh_from_db()
    assert profile.bond_amount == 500


@pytest.mark.django_db
def test_stock_decrement_updates_inventory(listing) -> None:
    result = decrement_stock(listing.pk, 2)

    listing.refresh_from_db()
    assert result.pk == listing.pk
    assert listing.stock == 3


@pytest.mark.django_db
def test_listing_price_is_formatted_without_float_rounding(listing) -> None:
    assert listing.price_base == "1.23456789"


@pytest.mark.django_db
def test_stock_decrement_rejects_insufficient_stock_without_mutation(listing) -> None:
    with pytest.raises(InsufficientStock):
        decrement_stock(listing.pk, 6)

    listing.refresh_from_db()
    assert listing.stock == 5


@pytest.mark.django_db
def test_stock_decrement_rejects_inactive_listing(listing) -> None:
    listing.is_active = False
    listing.save(update_fields=("is_active",))

    with pytest.raises(ListingUnavailable):
        decrement_stock(listing.pk)

    listing.refresh_from_db()
    assert listing.stock == 5


@pytest.mark.django_db
def test_stock_decrement_rejects_non_positive_quantity(listing) -> None:
    with pytest.raises(ValueError):
        decrement_stock(listing.pk, 0)

    with pytest.raises(TypeError):
        decrement_stock(listing.pk, True)

    listing.refresh_from_db()
    assert listing.stock == 5


@pytest.mark.django_db(transaction=True)
def test_concurrent_stock_decrements_do_not_oversell(listing) -> None:
    if connections["default"].vendor != "postgresql":
        pytest.skip("select_for_update concurrency requires PostgreSQL.")

    barrier = Barrier(2)

    def decrement() -> str:
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                decrement_stock(listing.pk, 4)
            except InsufficientStock:
                return "insufficient"
            return "decremented"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: decrement(), range(2)))

    listing.refresh_from_db()
    assert sorted(outcomes) == ["decremented", "insufficient"]
    assert listing.stock == 1
