from django.core.exceptions import ValidationError

from core.models import Notification


def notify_user(user, notification_type: str, message: str, data=None, actor=None):
    if user is None or user.pk is None:
        raise ValidationError("A persisted notification recipient is required.")
    if notification_type not in Notification.Type.values:
        raise ValidationError("Choose a valid notification type.")
    if not isinstance(message, str) or not message.strip() or len(message) > 255:
        raise ValidationError("Notification messages must contain 1 to 255 characters.")
    return Notification.objects.create(
        recipient=user,
        actor=actor,
        type=notification_type,
        message=message.strip(),
        data=data,
    )
