from django.contrib import admin

from .models import Reservation, ReservationHistory, RestaurantTable


@admin.register(RestaurantTable)
class RestaurantTableAdmin(admin.ModelAdmin):
    list_display = ("code", "capacity", "zone", "is_active")
    list_filter = ("zone", "is_active")
    search_fields = ("code",)
    ordering = ("sort_order", "code")


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = (
        "number_display",
        "guest_name",
        "phone",
        "date",
        "start_time",
        "end_time",
        "table",
        "status",
        "source",
        "responsible_employee",
    )
    list_filter = ("date", "status", "source")
    search_fields = ("guest_name", "phone")
    list_select_related = ("table", "responsible_employee")
    date_hierarchy = "date"

    @admin.display(description="Номер", ordering="id")
    def number_display(self, obj):
        return obj.number


@admin.register(ReservationHistory)
class ReservationHistoryAdmin(admin.ModelAdmin):

    list_display = ("reservation", "action", "old_status", "new_status", "actor", "created_at")
    list_filter = ("action",)
    search_fields = ("reservation__guest_name",)
    list_select_related = ("reservation", "actor")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
