from pathlib import Path

from django import forms
from django.conf import settings
from django.forms.renderers import DjangoTemplates
from django.utils.functional import cached_property


class KolaFormRenderer(DjangoTemplates):
    """Add the shared form control class while preserving widget attributes."""

    field_template_name = "forms/field.html"
    form_template_name = "forms/form.html"
    formset_template_name = "forms/formset.html"

    @cached_property
    def engine(self):
        return self.backend(
            {
                "APP_DIRS": True,
                "DIRS": [
                    settings.BASE_DIR / "mk" / "templates",
                    Path(forms.__file__).parent / "templates",
                ],
                "NAME": "kolaforms",
                "OPTIONS": {},
            }
        )

    def render(self, template_name, context, request=None):
        template_name = {
            "django/forms/div.html": self.form_template_name,
            "django/forms/formsets/div.html": self.formset_template_name,
        }.get(template_name, template_name)
        field = context.get("field") if hasattr(context, "get") else None
        if field is not None and getattr(field, "errors", None):
            attrs = field.field.widget.attrs
            attrs["aria-invalid"] = "true"
            error_id = f"{field.auto_id}_errors" if field.auto_id else ""
            described_by = attrs.get("aria-describedby", "").split()
            if error_id and error_id not in described_by:
                described_by.append(error_id)
                attrs["aria-describedby"] = " ".join(described_by)
        widget = context.get("widget") if hasattr(context, "get") else None
        if isinstance(widget, dict) and isinstance(widget.get("attrs"), dict):
            attrs = widget["attrs"]
            if not widget.get("is_hidden"):
                current = attrs.get("class", "").split()
                if "field__control" not in current:
                    current.append("field__control")
                attrs["class"] = " ".join(current)
        return super().render(template_name, context, request=request)
