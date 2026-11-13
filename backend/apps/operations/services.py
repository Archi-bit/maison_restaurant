from django.db import IntegrityError, transaction

from apps.staff.models import EmployeeProfile

from .models import RestaurantShift, ShiftEmployee, ShiftTableAssignment


class OperationBusinessError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


def get_current_shift():
    return RestaurantShift.objects.filter(status=RestaurantShift.Status.OPEN).first()


def open_shift(*, actor):
    try:
        with transaction.atomic():
            return RestaurantShift.objects.create(opened_by=actor)
    except IntegrityError as error:
        diagnostics = getattr(error.__cause__, "diag", None)
        if getattr(diagnostics, "constraint_name", None) != "operations_only_one_open_shift":
            raise
        raise OperationBusinessError(
            "shift_already_open", "Смена уже открыта."
        ) from error


def _lock_open_shift(shift):
    locked_shift = RestaurantShift.objects.select_for_update().get(pk=shift.pk)
    if locked_shift.status != RestaurantShift.Status.OPEN:
        raise OperationBusinessError("shift_closed", "Смена закрыта.")
    return locked_shift


@transaction.atomic
def add_shift_employee(*, shift, employee, actor):
    shift = _lock_open_shift(shift)
    if not employee.user.is_active:
        raise OperationBusinessError("inactive_employee", "Сотрудник неактивен.")
    if shift.employees.filter(employee=employee).exists():
        raise OperationBusinessError(
            "employee_already_added", "Сотрудник уже добавлен в смену."
        )
    return shift.employees.create(employee=employee)


@transaction.atomic
def assign_shift_table(*, shift, table, waiter, actor):
    shift = _lock_open_shift(shift)
    if not table.is_active:
        raise OperationBusinessError("inactive_table", "Стол неактивен.")
    if waiter.role != EmployeeProfile.Role.WAITER:
        raise OperationBusinessError(
            "invalid_waiter_role", "Назначить можно только официанта."
        )
    if not waiter.user.is_active:
        raise OperationBusinessError("inactive_employee", "Официант неактивен.")
    if not shift.employees.filter(employee=waiter).exists():
        raise OperationBusinessError(
            "waiter_not_in_shift", "Официант не добавлен в смену."
        )

    assignment = ShiftTableAssignment.objects.filter(shift=shift, table=table).first()
    if assignment is None:
        assignment = ShiftTableAssignment.objects.create(
            shift=shift, table=table, waiter=waiter
        )
        return assignment, True
    if assignment.waiter_id != waiter.pk:
        raise OperationBusinessError(
            "table_already_assigned", "Стол уже закреплён за другим официантом."
        )
    return assignment, False


def get_shift_tables(*, shift):
    return (
        ShiftTableAssignment.objects.filter(shift=shift)
        .select_related("table")
        .order_by("id")
    )


def get_waiter_tables(*, shift, waiter):
    return get_shift_tables(shift=shift).filter(waiter=waiter)
