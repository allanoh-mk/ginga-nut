from django.contrib import admin

from payments.models import MoneroOrderEscrow, MoneroOrderEscrowEvent


@admin.register(MoneroOrderEscrow)
class MoneroOrderEscrowAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = (
        "order",
        "state",
        "external_id",
        "expected_amount_atomic",
        "received_amount_atomic",
        "updated_at",
    )
    list_filter = ("state",)
    search_fields = ("order__id", "external_id", "settlement_transaction_id")
    readonly_fields = tuple(field.name for field in MoneroOrderEscrow._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False


@admin.register(MoneroOrderEscrowEvent)
class MoneroOrderEscrowEventAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("event_id", "escrow", "sequence", "event_type", "created_at")
    list_filter = ("event_type",)
    search_fields = ("event_id", "escrow__external_id")
    readonly_fields = tuple(field.name for field in MoneroOrderEscrowEvent._meta.fields)

    def has_add_permission(self, request) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
