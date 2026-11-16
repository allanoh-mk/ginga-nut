from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import User


@transaction.atomic
def update_session_expiry(user: User, expiry_seconds: int) -> User:
    allowed_values = {choice.value for choice in User.SessionExpiry}
    if expiry_seconds not in allowed_values:
        raise ValidationError("Choose a supported session duration.")

    user.session_expiry_seconds = expiry_seconds
    user.save(update_fields=("session_expiry_seconds",))
    return user
