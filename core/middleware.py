from django.conf import settings
from django.contrib.auth import logout
from django.core.exceptions import DisallowedHost
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse


class OnionHostMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if settings.ONION_ONLY:
            try:
                host = request.get_host().lower().partition(":")[0]
            except DisallowedHost:
                return HttpResponseBadRequest("Invalid Host header.")
            if host not in settings.ONION_HOSTS:
                return HttpResponseBadRequest("Invalid Host header.")
        return self.get_response(request)


class PGPAuthenticationMiddleware:
    def __init__(self, get_response) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            settings.ONION_ONLY
            and request.user.is_authenticated
            and request.session.get("pgp_verified_user_id") != request.user.pk
        ):
            logout(request)
            login_path = reverse("accounts:login")
            if request.path_info != login_path:
                return redirect(login_path)
        return self.get_response(request)
