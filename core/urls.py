from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.notification_list, name="notifications"),
    path("mark-all-read/", views.mark_notifications_read, name="mark-all-read"),
    path("<int:notification_id>/", views.open_notification, name="open-notification"),
]
