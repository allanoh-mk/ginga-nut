from django.contrib import admin

from catalog.models import Category, Listing, VendorProfile


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    prepopulated_fields = {"slug": ("name",)}
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(VendorProfile)
class VendorProfileAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("user", "bond_amount", "is_approved", "created_at")
    list_filter = ("is_approved",)
    search_fields = ("user__username",)
    readonly_fields = (
        "user",
        "bond_amount",
        "bond_account",
        "is_approved",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    class Media:
        css = {"all": ("css/admin.css",)}

    list_display = ("title", "vendor", "category", "price", "stock", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("title", "vendor__user__username")
    readonly_fields = tuple(
        field.name for field in Listing._meta.fields if field.name != "is_active"
    )
    list_editable = ("is_active",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
