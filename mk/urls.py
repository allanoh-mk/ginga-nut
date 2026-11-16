"""
URL configuration for mk project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.shortcuts import render
from django.urls import include, path

from core import views as core_views
from core.static_views import site_stylesheet
from core.views import home, how_it_works


def page_not_found(request, exception):
    return render(request, "404.html", status=404)


def server_error(request):
    return render(request, "500.html", status=500)


def bad_request(request, exception):
    return render(request, "400.html", status=400)


def access_denied(request, exception):
    return render(request, "403.html", status=403)


handler404 = "mk.urls.page_not_found"
handler500 = "mk.urls.server_error"
handler400 = "mk.urls.bad_request"
handler403 = "mk.urls.access_denied"

urlpatterns = [
    path("", home, name="home"),
    path("how-it-works/", how_it_works, name="how-it-works"),
    path("paused/new-orders/", core_views.paused_new_orders, name="paused-new-orders"),
    path(
        "paused/withdrawals/", core_views.paused_withdrawals, name="paused-withdrawals"
    ),
    path(
        "paused/digital-listings/",
        core_views.paused_digital_listings,
        name="paused-digital-listings",
    ),
    path("errors/400/", core_views.error_400, name="error-400"),
    path("errors/403/", core_views.error_403, name="error-403"),
    path("errors/404/", core_views.error_404, name="error-404"),
    path("errors/500/", core_views.error_500, name="error-500"),
    path("static/css/site.css", site_stylesheet, name="site-stylesheet"),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("catalog/", include("catalog.urls")),
    path("orders/", include("orders.urls")),
    path("payments/", include("payments.urls")),
    path("notifications/", include("core.urls")),
    path("", include("ops.urls")),
]
