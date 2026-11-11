from datetime import time

from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.reservations.models import Reservation, RestaurantTable

from . import future_date


def make_reservation(**overrides):
    data = {
        "guest_name": "Айбек",
        "phone": "+996700123456",
        "date": future_date(),
        "start_time": time(14, 0),
        "end_time": time(16, 0),
        "guests_count": 2,
    }
    data.update(overrides)
    return Reservation.objects.create(**data)


class ModelTests(TestCase):
    def test_reservation_defaults(self):
        r = make_reservation()
        self.assertEqual(r.status, Reservation.Status.PENDING)
        self.assertEqual(r.source, Reservation.Source.WEBSITE)
        self.assertIsNone(r.table)
        self.assertIsNone(r.created_by)
        self.assertIsNone(r.responsible_employee)

    def test_number_format(self):
        r = make_reservation()
        self.assertEqual(r.number, f"B-{r.pk:03d}")

    def test_table_code_unique(self):
        RestaurantTable.objects.create(code="T01", capacity=2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RestaurantTable.objects.create(code="T01", capacity=4)

    def test_table_default_zone(self):
        t = RestaurantTable.objects.create(code="T01", capacity=2)
        self.assertEqual(t.zone, "Основной зал")
        self.assertTrue(t.is_active)

    def test_guests_count_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(guests_count=7)

    def test_end_after_start_constraint(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reservation(start_time=time(16, 0), end_time=time(14, 0))
