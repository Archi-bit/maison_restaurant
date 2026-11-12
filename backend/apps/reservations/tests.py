from datetime import date, time, timedelta
from django.test import TestCase
from django.utils import timezone
from apps.reservations.models import RestaurantTable, Reservation, ReservationHistory
from apps.reservations.services import (
    create_public_reservation,
    create_staff_reservation,
    confirm_reservation,
    assign_table,
    get_hall_plan,
    ReservationBusinessError,
)


class ReservationServicesTestCase(TestCase):

    def setUp(self):
        # Создаем тестовый стол
        self.table = RestaurantTable.objects.create(
            code="T01",
            capacity=4,
            zone="Основной зал",
            is_active=True
        )
        # Будущая дата для тестов
        self.future_date = date.today() + timedelta(days=1)

    def test_create_public_reservation_success(self):
        """Успешное создание публичной брони через сайт."""
        data = {
            "guest_name": "Иван Иванов",
            "phone": "+996555123456",
            "date": self.future_date,
            "start_time": time(14, 0),
            "guests_count": 2,
        }
        reservation = create_public_reservation(validated_data=data)
        self.assertEqual(reservation.status, "pending")
        self.assertEqual(reservation.source, "website")
        self.assertIsNone(reservation.table)

    def test_confirm_reservation_requires_table(self):
        """Проверка требования: нельзя подтвердить бронь без назначенного стола (table_required)."""
        data = {
            "guest_name": "Петр Петров",
            "phone": "+996555654321",
            "date": self.future_date,
            "start_time": time(15, 0),
            "guests_count": 2,
        }
        reservation = create_public_reservation(validated_data=data)

        # Пытаемся подтвердить без стола — должно вызвать ReservationBusinessError с кодом "table_required"
        with self.assertRaises(ReservationBusinessError) as ctx:
            confirm_reservation(reservation=reservation, actor=None)

        self.assertEqual(ctx.exception.code, "table_required")

    def test_assign_table_and_confirm(self):
        """Назначение стола и успешное подтверждение брони."""
        data = {
            "guest_name": "Анна Смирнова",
            "phone": "+996555987654",
            "date": self.future_date,
            "start_time": time(18, 0),
            "guests_count": 3,
        }
        reservation = create_public_reservation(validated_data=data)

        # Назначаем стол
        assign_table(reservation=reservation, table=self.table, actor=None)
        self.assertEqual(reservation.table, self.table)

        # Теперь подтверждение должно пройти успешно
        confirm_reservation(reservation=reservation, actor=None)
        self.assertEqual(reservation.status, "confirmed")

    def test_get_hall_plan(self):
        """Проверка работы плана зала."""
        plan = get_hall_plan(date=self.future_date, time=time(14, 0), duration_minutes=120)
        self.assertIn("tables", plan)
        self.assertEqual(len(plan["tables"]), 1)
        self.assertEqual(plan["tables"][0]["status"], "free")