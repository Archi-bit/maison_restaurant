from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from phonenumber_field.modelfields import PhoneNumberField

STATUS_CHOSE = (
    ("pending", "Ожидает подтверждения"),
    ("confirmed", "Подтверждена"),
    ("arrived", "Гость пришёл"),
    ("cancelled", "Отменена"),
)

SOURCE_CHOSE = (
    ("website", "Сайт"),
    ("phone", "Телефон"),
    ("walk_in", "Гость без брони"),
)


class RestaurantTable(models.Model):
    code = models.CharField("code", max_length=6, unique=True)
    capacity = models.PositiveSmallIntegerField("capacity")
    zone = models.CharField("zone", max_length=50)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField("is active", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.code


class Reservation(models.Model):
    guest_name = models.CharField(max_length=150)
    phone = PhoneNumberField(max_length=20)
    guest_note = models.TextField(null=True, blank=True)
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    guests_count = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(6)]
    )
    status = models.CharField("status", max_length=20, choices=STATUS_CHOSE)
    source = models.CharField("source", max_length=20, choices=SOURCE_CHOSE)
    table = models.ForeignKey(
        RestaurantTable, on_delete=models.SET_NULL, null=True, blank=True
    )
    responsible_employee = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_reservations",
    )
    created_by = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_reservations",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def number(self):
        if self.pk is None:
            return "—"
        return f"B-{self.pk:03d}"

    def __str__(self):
        return self.guest_name


class ReservationHistory(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.CASCADE)
    actor = models.ForeignKey(
        "staff.EmployeeProfile", on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=40)
    old_status = models.CharField("old status", max_length=20, choices=STATUS_CHOSE)
    new_status = models.CharField("new status", max_length=20, choices=STATUS_CHOSE)
    details = models.TextField("detail", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.action
