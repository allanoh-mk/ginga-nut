from django.contrib.admin.apps import AdminConfig


class PGPAdminConfig(AdminConfig):
    default_site = "accounts.admin_site.PGPAdminSite"
