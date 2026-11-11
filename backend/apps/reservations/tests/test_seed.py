from io import StringIO

from django.core.management import call_command
from django.db.models import Sum

from apps.reservations.models import Reservation, RestaurantTable
from apps.reservations.services import assign_table, create_public_reservation

from . import ActorTestCase, public_data


def seed():
    call_command("seed_restaurant_tables", stdout=StringIO())


class SeedTests(ActorTestCase):
    def test_creates_12_tables_40_seats(self):
        seed()
        self.assertEqual(RestaurantTable.objects.count(), 12)
        self.assertEqual(RestaurantTable.objects.aggregate(s=Sum("capacity"))["s"], 40)
        self.assertEqual(
            set(RestaurantTable.objects.values_list("zone", flat=True)), {"Основной зал"}
        )
        self.assertEqual(RestaurantTable.objects.get(code="T12").capacity, 6)

    def test_second_run_no_duplicates(self):
        seed()
        seed()
        self.assertEqual(RestaurantTable.objects.count(), 12)

    def test_rerun_keeps_reservations(self):
        seed()
        r = create_public_reservation(validated_data=public_data())
        assign_table(reservation=r, table=RestaurantTable.objects.get(code="T05"), actor=self.actor)
        seed()
        r.refresh_from_db()
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(r.table.code, "T05")
