from rest_framework.permissions import BasePermission

from apps.staff.models import EmployeeProfile
from apps.staff.permissions import get_employee_profile


MANAGER_ROLES = (EmployeeProfile.Role.OWNER, EmployeeProfile.Role.ADMINISTRATOR)
ORDER_ROLES = (*MANAGER_ROLES, EmployeeProfile.Role.WAITER)
KITCHEN_ROLES = (*MANAGER_ROLES, EmployeeProfile.Role.CHEF)


class HasOrderRole(BasePermission):
    def has_permission(self, request, view):
        employee = get_employee_profile(request.user)
        return employee is not None and employee.role in view.allowed_roles
