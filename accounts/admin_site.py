from django.contrib.admin import AdminSite
from django.shortcuts import redirect


class PGPAdminSite(AdminSite):
    def has_permission(self, request) -> bool:
        return (
            super().has_permission(request)
            and request.session.get("pgp_verified_user_id") == request.user.pk
        )

    def login(self, request, extra_context=None):
        return redirect("accounts:login")
