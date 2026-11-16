from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from ledger.models import Account


class VendorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="vendor_profile",
    )
    bond_account = models.OneToOneField(
        Account,
        on_delete=models.PROTECT,
        related_name="vendor_profile",
    )
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def bond_amount(self) -> int:
        if self.bond_account_id is None:
            return 0
        return self.bond_account.balance

    def __str__(self) -> str:
        return f"Vendor profile for {self.user.username}"


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "categories"

    def __str__(self) -> str:
        return self.name


class Listing(models.Model):
    vendor = models.ForeignKey(
        VendorProfile,
        on_delete=models.PROTECT,
        related_name="listings",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="listings",
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    price = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    stock = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=True)
    image = models.ImageField(
        upload_to="catalog/listings/",
        null=True,
        blank=True,
    )
    shipping_required = models.BooleanField(default=True)
    delivery_zone = models.ForeignKey(
        "orders.DeliveryZone",
        on_delete=models.PROTECT,
        related_name="listings",
        null=True,
        blank=True,
    )
    average_rating = models.FloatField(default=0)
    review_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title",)

    def __str__(self) -> str:
        return self.title

    @property
    def price_base(self) -> str:
        whole, fraction = divmod(self.price, 100_000_000)
        return f"{whole}.{fraction:08d}"


class Review(models.Model):
    order = models.OneToOneField(
        "orders.Order",
        on_delete=models.CASCADE,
        related_name="review",
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True, max_length=2000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1, rating__lte=5),
                name="catalog_review_rating_1_to_5",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        if self.order_id and self.order.state != "FINALIZED":
            raise ValidationError("Only finalized orders can be reviewed.")

    def __str__(self) -> str:
        return f"Review for order {self.order_id}"
