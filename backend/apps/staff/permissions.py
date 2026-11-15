from rest_framework.permissions import SAFE_METHODS, BasePermission
from .models import EmployeeProfile



def get_employee_profile(user):
    if user.is_authenticated and user.is_active:
        return getattr(user, "employee_profile", None)
    return None


class HasEmployeeProfile(BasePermission):
    def has_permission(self, request, view):
        return get_employee_profile(request.user) is not None


class IsOwnerOrAdministrator(BasePermission):
    def has_permission(self, request, view):
        employee = get_employee_profile(request.user)
        return employee is not None and employee.role in (
            EmployeeProfile.Role.OWNER,
            EmployeeProfile.Role.ADMINISTRATOR,
        )


class IsAssignedWaiter(BasePermission):
    def has_permission(self, request, view):
        employee = get_employee_profile(request.user)
        return (
            request.method in SAFE_METHODS
            and employee is not None
            and employee.role == EmployeeProfile.Role.WAITER
        )

    def has_object_permission(self, request, view, obj):
        return (
            self.has_permission(request, view)
            and obj.responsible_employee_id == request.user.employee_profile.pk
        )
