from django.contrib import admin
from .models import RestaurantTable, Reservation, ReservationHistory


@admin.register(RestaurantTable)
class RestaurantTableAdmin(admin.ModelAdmin):
    list_display = ("code", "capacity", "zone", "sort_order", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("code", "zone")
    list_editable = ("capacity", "sort_order", "is_active")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "guest_name",
        "phone",
        "date",
        "start_time",
        "end_time",
        "guests_count",
        "status",
        "source",
        "table",
    )
    list_filter = ("status", "source", "date", "table__zone")
    search_fields = ("guest_name", "phone")
    readonly_fields = ("created_at", "updated_at", "number")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ReservationHistory)
class ReservationHistoryAdmin(admin.ModelAdmin):
    list_display = ("reservation", "actor", "action", "old_status", "new_status", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("reservation__guest_name", "details")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
