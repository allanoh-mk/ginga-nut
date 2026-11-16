from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from accounts.models import User
from payments.models import Chain, PayoutAddress


class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username",)
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username"}),
        }

    password1 = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Confirm password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class RecoveryLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"autocomplete": "username"}),
    )
    password = forms.CharField(
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    recovery_code = forms.CharField(
        max_length=64,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "one-time-code"}),
    )


class PGPEnrollmentForm(forms.Form):
    public_key = forms.CharField(
        max_length=131_072,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 8, "autocomplete": "off"}),
    )
    signature = forms.CharField(
        max_length=32_768,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 8, "autocomplete": "off"}),
    )


class PGPChallengeForm(forms.Form):
    signature = forms.CharField(
        required=False,
        max_length=32_768,
        strip=False,
        widget=forms.Textarea(attrs={"rows": 8, "autocomplete": "off"}),
    )
    recovery_code = forms.CharField(
        required=False,
        max_length=64,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        signature = str(cleaned_data.get("signature") or "").strip()
        recovery_code = cleaned_data.get("recovery_code")
        if bool(signature) == bool(recovery_code):
            raise forms.ValidationError(
                "Enter either an OpenPGP signature or one recovery code."
            )
        cleaned_data["signature"] = signature
        return cleaned_data


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("session_expiry_seconds",)
        labels = {"session_expiry_seconds": "Session duration"}


class WalletAddressForm(forms.Form):
    address = forms.CharField(
        max_length=64,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )


class WalletSignatureForm(forms.Form):
    signature = forms.CharField(
        max_length=132,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )


class DepositAddressForm(forms.Form):
    chain = forms.ChoiceField(choices=Chain.choices)


class WithdrawalForm(forms.Form):
    payout_address = forms.ModelChoiceField(
        queryset=PayoutAddress.objects.none(),
        label="Verified payout address",
    )
    amount = forms.IntegerField(min_value=1)
    idempotency_key = forms.CharField(
        max_length=128,
        widget=forms.HiddenInput,
    )

    def __init__(
        self,
        *args,
        user,
        available_balance: int,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.fields["payout_address"].queryset = PayoutAddress.objects.filter(
            user=user,
            deleted_at__isnull=True,
            verified_at__isnull=False,
            available_after__lte=timezone.now(),
        ).order_by("chain", "label", "pk")
        self.fields["amount"] = forms.IntegerField(
            min_value=1,
            help_text=(
                "Enter the gross amount to debit in base units. The market keeps "
                "3%, rounded up to a base unit; the remainder is sent to your "
                "payout address."
            ),
        )
        self.available_balance = available_balance
        if available_balance > 0:
            self.fields["amount"].widget.attrs["max"] = available_balance

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount > self.available_balance:
            raise forms.ValidationError(
                f"Amount cannot exceed your available balance "
                f"({self.available_balance} base units)."
            )
        return amount


class PayoutAddressForm(forms.Form):
    chain = forms.ChoiceField(choices=Chain.choices)
    label = forms.CharField(max_length=64, strip=True)
    address = forms.CharField(
        max_length=255,
        strip=True,
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
    address_confirmation = forms.CharField(
        max_length=255,
        strip=True,
        label="Retype payout address",
        widget=forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false"}),
    )
