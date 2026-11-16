from django import forms

from catalog.models import Category, Listing
from orders.models import DeliveryZone


class ListingForm(forms.ModelForm):
    def clean_shipping_required(self):
        shipping_required = self.cleaned_data["shipping_required"]
        if not shipping_required:
            raise forms.ValidationError(
                "Digital listings are unavailable until digital fulfillment "
                "is supported."
            )
        return shipping_required

    class Meta:
        model = Listing
        fields = (
            "category",
            "title",
            "description",
            "price",
            "stock",
            "is_active",
            "image",
            "delivery_zone",
        )
        widgets = {
            "description": forms.Textarea(attrs={"rows": 6}),
        }
        help_texts = {
            "price": "Enter integer ledger units; 100,000,000 units equal 1 base.",
        }


class CheckoutForm(forms.Form):
    quantity = forms.IntegerField(min_value=1)
    shipping_address = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    shipping_phone = forms.CharField(max_length=32, required=False)
    delivery_zone = forms.ModelChoiceField(
        queryset=DeliveryZone.objects.none(),
        required=False,
    )

    def __init__(self, *args, listing: Listing, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.listing = listing
        self.fields["quantity"] = forms.IntegerField(
            min_value=1,
            max_value=listing.stock,
        )
        self.fields["quantity"].widget.attrs["max"] = listing.stock
        zones = DeliveryZone.objects.select_related("city").order_by(
            "city__name", "name"
        )
        if listing.delivery_zone_id is not None:
            zones = zones.filter(pk=listing.delivery_zone_id)
            self.fields["delivery_zone"].required = True
        self.fields["delivery_zone"].queryset = zones
        if listing.shipping_required:
            self.fields["shipping_address"].required = True
            self.fields["shipping_phone"].required = True

    def clean(self):
        cleaned_data = super().clean()
        if not self.listing.shipping_required:
            cleaned_data["shipping_address"] = ""
            cleaned_data["shipping_phone"] = ""
        return cleaned_data


class CartCheckoutForm(forms.Form):
    shipping_address = forms.CharField(
        max_length=255,
        widget=forms.Textarea(
            attrs={"rows": 3, "autocomplete": "shipping street-address"}
        ),
    )
    shipping_phone = forms.CharField(
        max_length=32,
        widget=forms.TextInput(attrs={"autocomplete": "tel"}),
    )


class CatalogSearchForm(forms.Form):
    q = forms.CharField(max_length=200, required=False, label="Search listings")
    category = forms.ModelChoiceField(
        queryset=Category.objects.none(),
        required=False,
        to_field_name="slug",
        empty_label="All categories",
    )
    sort = forms.ChoiceField(
        choices=(
            ("newest", "Newest"),
            ("price_asc", "Price: low to high"),
            ("price_desc", "Price: high to low"),
        ),
        required=False,
        initial="newest",
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(
            listings__is_active=True,
            listings__is_approved=True,
            listings__vendor__is_approved=True,
            listings__shipping_required=True,
        ).distinct()
        if not self.is_bound:
            self.fields["sort"].initial = "newest"


class VendorListingFilterForm(forms.Form):
    q = forms.CharField(max_length=200, required=False, label="Search by title")
    status = forms.ChoiceField(
        choices=(
            ("", "All listings"),
            ("active", "Active"),
            ("inactive", "Inactive"),
        ),
        required=False,
    )
