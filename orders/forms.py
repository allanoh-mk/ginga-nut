from django import forms

from orders.models import Dispute, PublicRuling
from orders.uploads import (
    validate_evidence_extension,
    validate_pack_photo_extension,
    validate_upload_size,
)


class PackOrderForm(forms.Form):
    photo = forms.ImageField(
        validators=[validate_pack_photo_extension, validate_upload_size],
    )


class DispatchOrderForm(forms.Form):
    courier_reference = forms.CharField(max_length=160)


class ProofOfDeliveryForm(forms.Form):
    token = forms.CharField(max_length=128, strip=False)


class OpenDisputeForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 5}))
    evidence_kind = forms.ChoiceField(choices=Dispute.EvidenceKind.choices)
    description = forms.CharField(max_length=500, required=False)
    attachment = forms.FileField(
        validators=[validate_evidence_extension, validate_upload_size],
    )


class DisputeEvidenceForm(forms.Form):
    kind = forms.ChoiceField(choices=Dispute.EvidenceKind.choices)
    description = forms.CharField(max_length=500, required=False)
    attachment = forms.FileField(
        validators=[validate_evidence_extension, validate_upload_size],
    )


class PublicRulingForm(forms.ModelForm):
    released_amount_base_units = forms.IntegerField(
        required=False,
        min_value=1,
        label="Amount released to vendor for a partial ruling (base units)",
    )

    amount_band = forms.RegexField(
        regex=r"^\d{1,20}-\d{1,20} base$",
        max_length=80,
        error_messages={"invalid": "Use an amount band formatted as `min-max base`."},
    )
    reason = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 5}),
        help_text="This reason is published with the ruling.",
    )

    class Meta:
        model = PublicRuling
        fields = ("amount_band", "category", "outcome", "reason")

    def clean_amount_band(self):
        amount_band = self.cleaned_data["amount_band"]
        lower, upper = amount_band.removesuffix(" base").split("-", maxsplit=1)
        if int(lower) > int(upper):
            raise forms.ValidationError(
                "The lower amount must not exceed the upper amount."
            )
        return amount_band


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        choices=tuple((value, f"{value} star") for value in range(1, 6)),
        coerce=int,
    )
    comment = forms.CharField(
        max_length=2000,
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
