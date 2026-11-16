import pytest
from django.urls import reverse

from accounts.models import User
from catalog.models import Category, Listing
from core.services.create_vendor_profile import create_vendor_profile


@pytest.fixture
def discovery_catalog(db):
    vendor_user = User.objects.create_user(username="search-vendor")
    vendor = create_vendor_profile(vendor_user)
    vendor.is_approved = True
    vendor.save(update_fields=("is_approved",))
    home = Category.objects.create(name="Home", slug="home")
    books = Category.objects.create(name="Books", slug="books")
    return vendor_user, vendor, home, books


def _listing(vendor, category, title, description, price, *, active=True):
    return Listing.objects.create(
        vendor=vendor,
        category=category,
        title=title,
        description=description,
        price=price,
        stock=4,
        is_active=active,
    )


@pytest.mark.django_db
def test_catalog_search_matches_title_or_description(client, discovery_catalog):
    _, vendor, home, books = discovery_catalog
    _listing(vendor, home, "Blue kettle", "Steel kitchenware", 300)
    _listing(vendor, books, "Kitchen stories", "A guide to blue enamel", 200)
    _listing(vendor, books, "Other item", "Unrelated description", 100)

    response = client.get(reverse("catalog:search"), {"q": "blue"})

    assert response.status_code == 200
    assert b"Blue kettle" in response.content
    assert b"Kitchen stories" in response.content
    assert b"Other item" not in response.content


@pytest.mark.django_db
def test_catalog_search_filters_category_and_sorts_by_price(
    client,
    discovery_catalog,
):
    _, vendor, home, books = discovery_catalog
    _listing(vendor, home, "Low price", "Test item", 100)
    _listing(vendor, books, "Middle price", "Test item", 200)
    _listing(vendor, books, "High price", "Test item", 300)

    response = client.get(
        reverse("catalog:search"),
        {"category": "books", "sort": "price_asc"},
    )

    content = response.content.decode()
    assert response.status_code == 200
    assert "Low price" not in content
    assert content.index("Middle price") < content.index("High price")


@pytest.mark.django_db
def test_vendor_dashboard_filters_own_listings_by_status_and_title(
    client,
    discovery_catalog,
):
    vendor_user, vendor, home, _ = discovery_catalog
    for index in range(10):
        _listing(
            vendor,
            home,
            f"Item {index}",
            "Vendor inventory",
            100 + index,
            active=index < 5,
        )
    client.force_login(vendor_user)

    active_response = client.get(
        reverse("catalog:vendor-dashboard"),
        {"status": "active", "q": "Item"},
    )

    assert active_response.status_code == 200
    for index in range(5):
        assert f"Item {index}".encode() in active_response.content
    for index in range(5, 10):
        assert f"Item {index}".encode() not in active_response.content

    inactive_response = client.get(
        reverse("catalog:vendor-dashboard"),
        {"status": "inactive", "q": "Item 8"},
    )
    assert b"Item 8" in inactive_response.content
    assert b"Item 7" not in inactive_response.content
