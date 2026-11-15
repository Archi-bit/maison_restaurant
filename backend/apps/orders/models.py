from decimal import Decimal
from django.db import models
from django.db.models import Q


class Order(models.Model):
    CHANNEL_CHOICES = [
        ("dine_in", "В зале"),
        ("takeaway", "С собой"),
        ("delivery", "Доставка"),
    ]

    STATUS_CHOICES = [
        ("draft", "Черновик"),
        ("new", "Новый для кухни"),
        ("preparing", "Готовится"),
        ("ready", "Готов"),
        ("served", "Подан"),
        ("closed", "Закрыт"),
        ("cancelled", "Отменён"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("cash", "Наличные"),
        ("card", "Карта"),
    ]

    shift = models.ForeignKey(
        "operations.RestaurantShift", on_delete=models.PROTECT
    )
    channel = models.CharField(max_length=12, choices=CHANNEL_CHOICES)
    reservation = models.ForeignKey(
        "reservations.Reservation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    table = models.ForeignKey(
        "reservations.RestaurantTable",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )
    created_by = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_orders",
    )
    waiter = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="waiter_orders",
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="draft"
    )
    note = models.TextField(blank=True)
    is_paid = models.BooleanField(default=False)
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_METHOD_CHOICES, blank=True
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_by = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="paid_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reservation"],
                condition=Q(reservation__isnull=False),
                name="order_unique_reservation",
            )
        ]

    @property
    def number(self):
        if self.pk is None:
            return "---"
        return f"№{self.pk:04d}"

    @property
    def total(self):
        return sum(
            (item.line_total for item in self.items.all()), Decimal("0.00")
        )

    def __str__(self):
        return self.number


class OrderItem(models.Model):
    STATION_CHOICES = [
        ("hot", "Горячий цех"),
        ("cold", "Холодный цех"),
    ]

    order = models.ForeignKey(
        "orders.Order", on_delete=models.CASCADE, related_name="items"
    )
    dish = models.ForeignKey("catalog.Dish", on_delete=models.PROTECT)
    dish_name = models.CharField(max_length=200)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveSmallIntegerField()
    note = models.CharField(max_length=255, blank=True)
    station = models.CharField(max_length=10, choices=STATION_CHOICES)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.dish_name} x{self.quantity}"


class OrderHistory(models.Model):
    ACTION_CHOICES = [
        ("created", "Создан"),
        ("item_added", "Позиция добавлена"),
        ("item_updated", "Позиция изменена"),
        ("item_removed", "Позиция удалена"),
        ("sent_to_kitchen", "Отправлен на кухню"),
        ("preparing", "Готовится"),
        ("ready", "Готов"),
        ("served", "Подан"),
        ("paid", "Оплачен"),
        ("closed", "Закрыт"),
        ("cancelled", "Отменён"),
    ]

    order = models.ForeignKey(
        "orders.Order", on_delete=models.CASCADE, related_name="history"
    )
    actor = models.ForeignKey(
        "staff.EmployeeProfile",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=40, choices=ACTION_CHOICES)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.order.number} - {self.action}"
