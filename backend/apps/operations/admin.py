from django.contrib import admin

from apps.staff.models import EmployeeProfile
from apps.staff.permissions import get_employee_profile

from .models import RestaurantShift, ShiftEmployee, ShiftTableAssignment


class ShiftReadOnlyAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        employee = get_employee_profile(request.user)
        return (
            employee is not None
            and employee.role in (EmployeeProfile.Role.OWNER, EmployeeProfile.Role.ADMINISTRATOR)
            and super().has_view_permission(request, obj)
        )

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RestaurantShift)
class RestaurantShiftAdmin(ShiftReadOnlyAdmin):
    list_display = ("id", "status", "opened_at", "opened_by", "closed_at", "closed_by")
    list_filter = ("status",)
    list_select_related = ("opened_by", "closed_by")


@admin.register(ShiftEmployee)
class ShiftEmployeeAdmin(ShiftReadOnlyAdmin):
    list_display = ("shift", "employee", "added_at")
    list_select_related = ("shift", "employee")


@admin.register(ShiftTableAssignment)
class ShiftTableAssignmentAdmin(ShiftReadOnlyAdmin):
    list_display = ("shift", "table", "waiter", "assigned_at")
    list_select_related = ("shift", "table", "waiter")
