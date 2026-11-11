from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class RestaurantTable(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.CharField("Код стола", max_length=10, unique=True)
    capacity = models.PositiveSmallIntegerField("Количество мест")
    zone = models.CharField("Зона", max_length=100, default="Основной зал")
    sort_order = models.PositiveSmallIntegerField("Порядок сортировки", default=0)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "code"]
        verbose_name = "Стол"
        verbose_name_plural = "Столы"

    def __str__(self):
        return f"{self.code} ({self.capacity} мест)"


class Reservation(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает подтверждения"
        CONFIRMED = "confirmed", "Подтверждена"
        ARRIVED = "arrived", "Гость пришёл"
        CANCELLED = "cancelled", "Отменена"

    class Source(models.TextChoices):
        WEBSITE = "website", "Сайт"
        PHONE = "phone", "Телефон"
        WALK_IN = "walk_in", "Гость без брони"

    id = models.BigAutoField(primary_key=True)

    guest_name = models.CharField("Имя гостя", max_length=150)
    phone = models.CharField("Телефон", max_length=32)
    guest_note = models.TextField("Комментарий гостя", blank=True, default="")

    date = models.DateField("Дата")
    start_time = models.TimeField("Начало")
    end_time = models.TimeField("Конец")
    guests_count = models.PositiveSmallIntegerField(
        "Количество гостей",
        validators=[MinValueValidator(1), MaxValueValidator(6)],
    )

    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    source = models.CharField(
        "Источник",
        max_length=20,
        choices=Source.choices,
        default=Source.WEBSITE,
    )

    table = models.ForeignKey(
        RestaurantTable,
        verbose_name="Стол",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reservations",
    )

    responsible_employee = models.ForeignKey(
        "staff.EmployeeProfile",
        verbose_name="Ответственный сотрудник",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="responsible_reservations",
    )
    created_by = models.ForeignKey(
        "staff.EmployeeProfile",
        verbose_name="Создал",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_reservations",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-start_time"]
        verbose_name = "Бронь"
        verbose_name_plural = "Брони"
        indexes = [
            models.Index(fields=["date", "status"]),
            models.Index(fields=["table", "date"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(guests_count__gte=1, guests_count__lte=6),
                name="reservation_guests_count_1_6",
            ),
            models.CheckConstraint(
                check=models.Q(end_time__gt=models.F("start_time")),
                name="reservation_end_after_start",
            ),
        ]

    @property
    def number(self):

        return f"B-{self.pk:03d}" if self.pk else ""

    def __str__(self):
        return f"{self.number} — {self.guest_name} ({self.date} {self.start_time:%H:%M})"


class ReservationHistory(models.Model):
    class Action(models.TextChoices):
        CREATED = "created", "Создана"
        UPDATED = "updated", "Изменена"
        CONFIRMED = "confirmed", "Подтверждена"
        TABLE_ASSIGNED = "table_assigned", "Назначен стол"
        ARRIVED = "arrived", "Гость пришёл"
        CANCELLED = "cancelled", "Отменена"

    id = models.BigAutoField(primary_key=True)
    reservation = models.ForeignKey(
        Reservation,
        on_delete=models.CASCADE,
        related_name="history",
    )
    actor = models.ForeignKey(
        "staff.EmployeeProfile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reservation_history_actions",
    )
    action = models.CharField("Действие", max_length=30, choices=Action.choices)
    old_status = models.CharField(max_length=20, blank=True, default="")
    new_status = models.CharField(max_length=20, blank=True, default="")
    details = models.TextField("Детали", blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name = "История брони"
        verbose_name_plural = "История броней"

    def __str__(self):
        return f"{self.reservation.number}: {self.action}"
