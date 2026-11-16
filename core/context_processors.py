def market_identity(request):
    user = request.user
    pagination_query = request.GET.copy()
    pagination_query.pop("page", None)
    context = {"pagination_query": pagination_query.urlencode()}
    if not user.is_authenticated:
        return context

    username = user.get_username()
    initials = username[0].upper() + (
        username[1].lower() if len(username) > 1 else username[0].lower()
    )
    if user.is_staff:
        role = "admin"
    elif user.groups.filter(name__iexact="delivery").exists():
        role = "delivery"
    elif hasattr(user, "vendor_profile"):
        role = "vendor"
    else:
        role = "customer"

    from core.models import Notification

    context.update(
        {
            "market_role": role,
            "market_initials": initials,
            "unread_notification_count": Notification.objects.filter(
                recipient=user,
                read_at__isnull=True,
            ).count(),
        }
    )
    return context
