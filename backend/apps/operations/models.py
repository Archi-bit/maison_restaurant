from django.db import models
from django.db.models import Q
from django.utils import timezone


class RestaurantShift(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Открыта"
        CLOSED = "closed", "Закрыта"

    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.OPEN
    )
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(
        "staff.EmployeeProfile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="opened_shifts",
    )
    closed_by = models.ForeignKey(
        "staff.EmployeeProfile", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="closed_shifts",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["status"],
                condition=Q(status="open"),
                name="operations_only_one_open_shift",
            )
        ]

    def __str__(self):
        return f"Смена №{self.pk}"


class ShiftEmployee(models.Model):
    shift = models.ForeignKey(
        RestaurantShift, on_delete=models.PROTECT, related_name="employees"
    )
    employee = models.ForeignKey("staff.EmployeeProfile", on_delete=models.PROTECT)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "employee"], name="unique_employee_in_shift"
            )
        ]

    def __str__(self):
        return f"{self.shift} — {self.employee}"


class ShiftTableAssignment(models.Model):
    shift = models.ForeignKey(RestaurantShift, on_delete=models.PROTECT)
    table = models.ForeignKey("reservations.RestaurantTable", on_delete=models.PROTECT)
    waiter = models.ForeignKey("staff.EmployeeProfile", on_delete=models.PROTECT)
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["shift", "table"], name="unique_table_assignment_per_shift"
            )
        ]

    def __str__(self):
        return f"{self.shift} — {self.table}"
