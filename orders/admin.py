from django.contrib import admin

from orders.models import (
    City,
    DeliveryZone,
    Dispute,
    DisputeEvidence,
    Order,
    PublicRuling,
)


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")


@admin.register(DeliveryZone)
class DeliveryZoneAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("name", "city")
    list_filter = ("city",)
    search_fields = ("name", "city__name")


class DisputeEvidenceInline(admin.TabularInline):
    model = DisputeEvidence
    extra = 0
    can_delete = False
    readonly_fields = (
        "submitted_by",
        "kind",
        "description",
        "attachment",
        "created_at",
    )

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Dispute)
class DisputeAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("id", "order", "filed_by", "created_at")
    list_filter = ("created_at",)
    search_fields = ("order__id", "filed_by__username")
    readonly_fields = ("order", "filed_by", "reason", "created_at")
    inlines = (DisputeEvidenceInline,)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PublicRuling)
class PublicRulingAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("id", "amount_band", "category", "outcome", "created_at")
    list_filter = ("outcome", "category")
    readonly_fields = ("dispute", "amount_band", "category", "outcome", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("id", "state", "buyer", "vendor", "courier_reference", "created_at")
    list_filter = ("state", "delivery_lane")
    search_fields = ("id", "courier_reference", "listing_title")
    readonly_fields = tuple(field.name for field in Order._meta.fields)
