import threading
import unittest
from datetime import time

from django.db import connection
from django.test import TransactionTestCase

from apps.reservations.models import RestaurantTable
from apps.reservations.services import (
    ReservationBusinessError,
    assign_table,
    cancel_reservation,
    confirm_reservation,
    create_public_reservation,
    get_hall_plan,
    mark_arrived,
)

from . import ActorTestCase, future_date, make_actor, public_data


def code_of(exc_info):
    return exc_info.exception.code


class AssignTableTests(ActorTestCase):
    def setUp(self):
        self.small = RestaurantTable.objects.create(code="T01", capacity=2, sort_order=1)
        self.big = RestaurantTable.objects.create(code="T02", capacity=4, sort_order=2)
        self.off = RestaurantTable.objects.create(
            code="T03", capacity=4, sort_order=3, is_active=False
        )

    def reservation(self, **overrides):
        return create_public_reservation(validated_data=public_data(**overrides))

    def test_assign_ok_writes_history(self):
        r = assign_table(reservation=self.reservation(), table=self.big, actor=self.actor)
        self.assertEqual(r.table, self.big)
        self.assertIn("table_assigned", list(r.history.values_list("action", flat=True)))

    def test_capacity_too_small(self):
        r = self.reservation(guests_count=3)
        with self.assertRaises(ReservationBusinessError) as ctx:
            assign_table(reservation=r, table=self.small, actor=self.actor)
        self.assertEqual(code_of(ctx), "table_too_small")

    def test_inactive_table(self):
        with self.assertRaises(ReservationBusinessError) as ctx:
            assign_table(reservation=self.reservation(), table=self.off, actor=self.actor)
        self.assertEqual(code_of(ctx), "table_inactive")

    def test_overlap_rejected(self):
        assign_table(reservation=self.reservation(), table=self.big, actor=self.actor)
        r2 = self.reservation(start_time=time(15, 0))  # 15:00–17:00 пересекается с 14:00–16:00
        with self.assertRaises(ReservationBusinessError) as ctx:
            assign_table(reservation=r2, table=self.big, actor=self.actor)
        self.assertEqual(code_of(ctx), "table_conflict")

    def test_adjacent_intervals_allowed(self):
        assign_table(reservation=self.reservation(), table=self.big, actor=self.actor)  # 14–16
        r2 = self.reservation(start_time=time(16, 0))  # 16–18
        r2 = assign_table(reservation=r2, table=self.big, actor=self.actor)
        self.assertEqual(r2.table, self.big)

    def test_cancel_frees_table(self):
        r1 = assign_table(reservation=self.reservation(), table=self.big, actor=self.actor)
        r2 = self.reservation()
        cancel_reservation(reservation=r1, actor=self.actor)
        r2 = assign_table(reservation=r2, table=self.big, actor=self.actor)
        self.assertEqual(r2.table, self.big)

    def test_other_date_does_not_conflict(self):
        assign_table(reservation=self.reservation(), table=self.big, actor=self.actor)
        r2 = self.reservation(date=future_date(5))
        r2 = assign_table(reservation=r2, table=self.big, actor=self.actor)
        self.assertEqual(r2.table, self.big)


class HallPlanTests(ActorTestCase):
    def setUp(self):
        self.t1 = RestaurantTable.objects.create(code="T01", capacity=2, sort_order=1)
        self.t2 = RestaurantTable.objects.create(code="T02", capacity=4, sort_order=2)
        self.date = future_date()

    def status_of(self, code, **kwargs):
        plan = get_hall_plan(date=self.date, time=time(14, 30), duration_minutes=30, **kwargs)
        return next(t["status"] for t in plan["tables"] if t["code"] == code)

    def test_all_free_by_default(self):
        self.assertEqual(self.status_of("T01"), "free")
        self.assertEqual(self.status_of("T02"), "free")

    def test_reservation_without_table_occupies_nothing(self):
        create_public_reservation(validated_data=public_data(date=self.date))
        self.assertEqual(self.status_of("T01"), "free")
        self.assertEqual(self.status_of("T02"), "free")

    def test_reserved_then_occupied(self):
        r = create_public_reservation(validated_data=public_data(date=self.date))
        r = assign_table(reservation=r, table=self.t2, actor=self.actor)
        self.assertEqual(self.status_of("T02"), "reserved")  # pending
        r = confirm_reservation(reservation=r, actor=self.actor)
        self.assertEqual(self.status_of("T02"), "reserved")  # confirmed
        mark_arrived(reservation=r, actor=self.actor)
        self.assertEqual(self.status_of("T02"), "occupied")  # arrived
        self.assertEqual(self.status_of("T01"), "free")

    def test_cancelled_is_free(self):
        r = create_public_reservation(validated_data=public_data(date=self.date))
        r = assign_table(reservation=r, table=self.t2, actor=self.actor)
        cancel_reservation(reservation=r, actor=self.actor)
        self.assertEqual(self.status_of("T02"), "free")

    def test_outside_window_is_free(self):
        r = create_public_reservation(validated_data=public_data(date=self.date))  # 14–16
        assign_table(reservation=r, table=self.t2, actor=self.actor)
        plan = get_hall_plan(date=self.date, time=time(17, 0), duration_minutes=60)
        self.assertTrue(all(t["status"] == "free" for t in plan["tables"]))

    def test_summary(self):
        plan = get_hall_plan(date=self.date, time=time(14, 0), duration_minutes=60)
        self.assertEqual(plan["summary"]["total"], 2)
        self.assertEqual(plan["summary"]["total_seats"], 6)


class HallPlanRestoreTests(ActorTestCase):
    def test_plan_is_derived_from_reservations_only(self):
        """Статусы стола нигде не хранятся: после отмены план возвращается в исходное состояние."""
        table = RestaurantTable.objects.create(code="T01", capacity=4)
        date = future_date()
        before = get_hall_plan(date=date, time=time(14, 30), duration_minutes=30)
        r = assign_table(
            reservation=create_public_reservation(validated_data=public_data(date=date)),
            table=table, actor=self.actor,
        )
        cancel_reservation(reservation=r, actor=self.actor)
        after = get_hall_plan(date=date, time=time(14, 30), duration_minutes=30)
        self.assertEqual(before["tables"][0]["status"], after["tables"][0]["status"])
        self.assertEqual(after["summary"]["free"], 1)

    def test_inactive_table_not_in_plan(self):
        RestaurantTable.objects.create(code="T01", capacity=4)
        RestaurantTable.objects.create(code="T02", capacity=4, is_active=False)
        plan = get_hall_plan(date=future_date(), time=time(14, 0), duration_minutes=60)
        self.assertEqual([t["code"] for t in plan["tables"]], ["T01"])


@unittest.skipUnless(
    connection.vendor == "postgresql", "select_for_update полноценно работает только в PostgreSQL"
)
class ConcurrentAssignTests(TransactionTestCase):
    def test_only_one_reservation_gets_the_table(self):
        actor = make_actor()
        table = RestaurantTable.objects.create(code="T10", capacity=4, sort_order=1)
        r1 = create_public_reservation(validated_data=public_data())
        r2 = create_public_reservation(validated_data=public_data(guest_name="Другой гость"))

        results = []
        barrier = threading.Barrier(2)

        def worker(reservation):
            try:
                barrier.wait()
                assign_table(reservation=reservation, table=table, actor=actor)
                results.append("ok")
            except ReservationBusinessError as exc:
                results.append(exc.code)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker, args=(r,)) for r in (r1, r2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sorted(results), ["ok", "table_conflict"])
