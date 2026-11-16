from django import forms

from orders.models import City, Order


class OrderFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        choices=(("", "All statuses"), *Order.State.choices),
    )
    city = forms.ModelChoiceField(
        required=False,
        queryset=City.objects.all(),
        empty_label="All cities",
    )
    start_date = forms.DateField(required=False, input_formats=("%Y-%m-%d",))
    end_date = forms.DateField(required=False, input_formats=("%Y-%m-%d",))

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        if start_date and end_date and start_date > end_date:
            raise forms.ValidationError("Start date must not be after end date.")
        return cleaned_data
