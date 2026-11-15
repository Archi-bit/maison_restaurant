from django.contrib import admin
from .models import Order, OrderItem, OrderHistory


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "get_number",
        "status",
        "channel",
        "table",
        "waiter",
        "is_paid",
        "created_at",
    )
    list_filter = ("status", "channel", "is_paid", "shift")
    search_fields = ("id", "table__code", "waiter__full_name")
    readonly_fields = (
        "id",
        "shift",
        "channel",
        "reservation",
        "table",
        "created_by",
        "waiter",
        "status",
        "note",
        "is_paid",
        "payment_method",
        "paid_at",
        "paid_by",
        "created_at",
        "updated_at",
        "closed_at",
    )

    def get_number(self, obj):
        return obj.number

    get_number.short_description = "Номер"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "dish_name", "quantity", "unit_price", "station")
    list_filter = ("station",)
    search_fields = ("dish_name", "order__id")
    readonly_fields = (
        "order",
        "dish",
        "dish_name",
        "unit_price",
        "quantity",
        "note",
        "station",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderHistory)
class OrderHistoryAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "action", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("order__id", "actor__full_name")
    readonly_fields = (
        "order",
        "actor",
        "action",
        "old_status",
        "new_status",
        "details",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
