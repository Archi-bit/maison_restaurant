from django.contrib import admin
from .models import EmployeeProfile
from .permissions import get_employee_profile



@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ("full_name", "work_email", "role", "is_active")
    list_select_related = ("user",)
    search_fields = ("full_name", "work_email")

    @admin.display(boolean=True, ordering="user__is_active", description="Активен")
    def is_active(self, employee):
        return employee.user.is_active

    def is_owner(self, request):
        employee = get_employee_profile(request.user)
        return employee is not None and employee.role == EmployeeProfile.Role.OWNER

    def has_module_permission(self, request):
        return self.is_owner(request) and super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self.is_owner(request) and super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self.is_owner(request) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.is_owner(request) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.is_owner(request) and super().has_delete_permission(request, obj)
