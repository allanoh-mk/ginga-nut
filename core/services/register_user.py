import unicodedata

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from accounts.models import User


@transaction.atomic
def register_user(username: str, password: str) -> User:
    if not username or not username.strip():
        raise ValidationError("A username is required.")
    username = unicodedata.normalize("NFKC", username.strip())
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError("That username is already taken.")

    user = User(username=username)
    validate_password(password, user=user)
    try:
        user.set_password(password)
        user.save(force_insert=True)
    except IntegrityError as exc:
        raise ValidationError("That username is already taken.") from exc
    return user
