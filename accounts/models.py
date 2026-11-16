import unicodedata

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(
        self, username: str, password: str | None = None, **extra_fields: object
    ):
        if not username:
            raise ValueError("A username is required.")
        normalized_username = self.model.normalize_username(username)
        user = self.model(username=normalized_username, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        username: str,
        password: str | None = None,
        **extra_fields: object,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self.create_user(username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    class SessionExpiry(models.IntegerChoices):
        THIRTY_MINUTES = 30 * 60, "30 minutes"
        ONE_HOUR = 60 * 60, "1 hour"
        TWO_HOURS = 2 * 60 * 60, "2 hours"

    username = models.CharField(max_length=150, unique=True)
    session_expiry_seconds = models.PositiveSmallIntegerField(
        choices=SessionExpiry.choices,
        default=SessionExpiry.THIRTY_MINUTES,
    )
    pgp_public_key = models.TextField(blank=True, default="")
    pgp_fingerprint = models.CharField(max_length=64, blank=True, default="")
    pgp_recovery_code_hashes = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    @staticmethod
    def normalize_username(username: str) -> str:
        return unicodedata.normalize("NFKC", username)

    def __str__(self) -> str:
        return self.username
