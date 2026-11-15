import csv
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Category, Dish
from apps.orders import services as order_services
from apps.orders.models import Order, OrderItem
from apps.reservations.models import RestaurantTable
from apps.staff.models import EmployeeProfile

from .models import RestaurantShift, ShiftEmployee, ShiftTableAssignment


PASSWORD = "Local-shift-test-42!"


def create_employee(username, role, *, is_active=True):
    user = get_user_model().objects.create_user(
        username=username, password=PASSWORD, is_active=is_active
    )
    return EmployeeProfile.objects.create(
        user=user, work_email=f"{username}@example.com", full_name=username, role=role
    )


class ShiftAPITests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = create_employee("owner", EmployeeProfile.Role.OWNER)
        cls.administrator = create_employee("administrator", EmployeeProfile.Role.ADMINISTRATOR)
        cls.waiter = create_employee("waiter", EmployeeProfile.Role.WAITER)
        cls.other_waiter = create_employee("other_waiter", EmployeeProfile.Role.WAITER)
        cls.chef = create_employee("chef", EmployeeProfile.Role.CHEF)
        cls.inactive = create_employee(
            "inactive", EmployeeProfile.Role.WAITER, is_active=False
        )
        cls.table = RestaurantTable.objects.create(code="T05", capacity=2, zone="Зал")
        cls.other_table = RestaurantTable.objects.create(code="T06", capacity=4, zone="Зал")
        cls.inactive_table = RestaurantTable.objects.create(
            code="T07", capacity=4, zone="Зал", is_active=False
        )
        cls.open_url = reverse("operations:shift-open")
        cls.current_url = reverse("operations:shift-current")
        cls.tables_url = reverse("operations:shift-current-tables")

    def authenticate(self, user):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(user)}")

    def create_shift(self):
        return RestaurantShift.objects.create(opened_by=self.owner)

    def employees_url(self, shift_id):
        return reverse("operations:shift-employees", args=[shift_id])

    def assignment_url(self, shift_id, table_id):
        return reverse("operations:shift-assign-table", args=[shift_id, table_id])

    def test_owner_login_and_open_shift(self):
        login = self.client.post(
            reverse("staff:login"),
            {"work_email": self.owner.work_email, "password": PASSWORD},
            format="json",
        )
        self.assertEqual(login.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        me = self.client.get(reverse("staff:me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.data["role"], EmployeeProfile.Role.OWNER)
        self.assertEqual(self.client.get(self.current_url).data, {"shift": None})
        self.assertEqual(self.client.get(self.tables_url).data, [])

        opened = self.client.post(self.open_url, {}, format="json")
        self.assertEqual(opened.status_code, 201)
        self.assertEqual(opened.data["status"], RestaurantShift.Status.OPEN)
        self.assertEqual(opened.data["opened_by"], self.owner.pk)
        self.assertIsNone(opened.data["closed_at"])
        self.assertEqual(self.client.get(self.current_url).data, opened.data)

        duplicate = self.client.post(self.open_url, {}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data["code"], "shift_already_open")
        self.assertEqual(RestaurantShift.objects.count(), 1)

    def test_administrator_can_add_and_list_shift_employees(self):
        self.authenticate(self.administrator.user)
        shift = self.create_shift()
        url = self.employees_url(shift.pk)
        for employee in (self.waiter, self.chef):
            response = self.client.post(url, {"employee_id": employee.pk}, format="json")
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["employee"], employee.pk)
            self.assertNotIn("work_email", response.data)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [member["employee"] for member in response.data], [self.waiter.pk, self.chef.pk]
        )
        duplicate = self.client.post(url, {"employee_id": self.waiter.pk}, format="json")
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data["code"], "employee_already_added")
        inactive = self.client.post(url, {"employee_id": self.inactive.pk}, format="json")
        self.assertEqual(inactive.status_code, 400)
        self.assertEqual(inactive.data["code"], "inactive_employee")
        self.assertEqual(shift.employees.count(), 2)

    def test_reassign_table_only_after_orders_on_it_are_finished(self):
        self.authenticate(self.administrator.user)
        shift = self.create_shift()
        for waiter in (self.waiter, self.other_waiter):
            shift.employees.create(employee=waiter)
        url = self.assignment_url(shift.pk, self.table.pk)
        payload = {"waiter_id": self.waiter.pk}
        assigned = self.client.put(url, payload, format="json")
        self.assertEqual(assigned.status_code, 201)
        self.assertEqual(assigned.data["table_code"], "T05")
        self.assertEqual(assigned.data["waiter"], self.waiter.pk)
        repeated = self.client.put(url, payload, format="json")
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.data, assigned.data)

        order = Order.objects.create(
            shift=shift, channel="dine_in", table=self.table, waiter=self.waiter
        )
        new_payload = {"waiter_id": self.other_waiter.pk}
        conflict = self.client.put(url, new_payload, format="json")
        self.assertEqual(conflict.status_code, 400)
        self.assertEqual(conflict.data["code"], "table_already_assigned")
        self.assertEqual(ShiftTableAssignment.objects.get().waiter_id, self.waiter.pk)

        order_services.cancel_order(order=order, reason="Ошибка ввода", actor=self.administrator)
        Order.objects.create(shift=shift, channel="dine_in", table=self.other_table)
        reassigned = self.client.put(url, new_payload, format="json")
        self.assertEqual(reassigned.status_code, 200)
        self.assertEqual(reassigned.data["id"], assigned.data["id"])
        self.assertEqual(ShiftTableAssignment.objects.get().waiter_id, self.other_waiter.pk)
        order.refresh_from_db()
        self.assertEqual(order.waiter_id, self.waiter.pk)

    def test_reservation_order_payment_and_shift_closing(self):
        self.authenticate(self.owner.user)
        opened = self.client.post(self.open_url)
        self.assertEqual(opened.status_code, 201)
        shift_id = opened.data["id"]
        member = self.client.post(self.employees_url(shift_id), {"employee_id": self.waiter.pk})
        self.assertEqual(member.status_code, 201)
        assignment = self.client.put(
            self.assignment_url(shift_id, self.table.pk), {"waiter_id": self.waiter.pk}
        )
        self.assertEqual(assignment.status_code, 201)

        reservation = self.client.post(
            reverse("reservation_api:staff-reservation-list"),
            {
                "guest_name": "Гость",
                "phone": "+996555010031",
                "date": (timezone.localdate() + timedelta(days=1)).isoformat(),
                "start_time": "20:30",
                "guests_count": 2,
                "source": "phone",
                "table_id": self.table.pk,
            },
            format="json",
        )
        self.assertEqual(reservation.status_code, 201)
        reservation_id = reservation.data["id"]
        for action in ("confirm", "arrive"):
            response = self.client.post(
                reverse(f"reservation_api:staff-reservation-{action}", args=[reservation_id])
            )
            self.assertEqual(response.status_code, 200)

        order = order_services.create_order(
            validated_data={"channel": "dine_in", "reservation_id": reservation_id},
            actor=self.waiter,
        )
        self.assertEqual(order.shift_id, shift_id)
        self.assertEqual(order.waiter_id, self.waiter.pk)

        close_url = reverse("operations:shift-close", args=[shift_id])
        blocked = self.client.post(close_url)
        self.assertEqual(blocked.status_code, 400)
        self.assertEqual(blocked.data["code"], "active_orders")
        self.assertEqual(self.client.get(self.current_url).data, opened.data)

        cancelled_order = order_services.create_order(
            validated_data={"channel": "delivery"}, actor=self.owner
        )
        order_services.cancel_order(
            order=cancelled_order, reason="Отмена гостем", actor=self.owner
        )
        category = Category.objects.create(name="Горячее", slug="hot")
        dish = Dish.objects.create(
            name="Стейк", slug="steak", category=category, price=Decimal("123.45")
        )
        order_services.add_order_item(order=order, dish=dish, quantity=2, note="", actor=self.waiter)
        order_services.send_to_kitchen(order=order, actor=self.waiter)
        order_services.start_preparing(order=order, actor=self.chef)
        order_services.mark_ready(order=order, actor=self.chef)
        order_services.mark_served(order=order, actor=self.waiter)
        paid_order = order_services.mark_paid(
            order=order, payment_method="card", actor=self.owner
        )
        self.assertEqual(self.client.post(close_url).data["code"], "active_orders")
        order_services.close_order(order=order, actor=self.owner)

        self.authenticate(self.administrator.user)
        closed = self.client.post(close_url)
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.data["status"], RestaurantShift.Status.CLOSED)
        self.assertEqual(closed.data["closed_by"], self.administrator.pk)
        self.assertIsNotNone(closed.data["closed_at"])
        self.assertEqual(self.client.get(self.current_url).data, {"shift": None})
        duplicate = self.client.post(close_url)
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(duplicate.data["code"], "shift_closed")
        paid_date = timezone.localdate(paid_order.paid_at).isoformat()
        summary = self.client.get(
            reverse("operations:sales-summary"), {"date_from": paid_date, "date_to": paid_date}
        )
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.data["revenue"], "246.90")
        self.assertEqual(summary.data["paid_orders_count"], 1)

        with self.assertRaises(order_services.OrderBusinessError) as error:
            order_services.create_order(validated_data={"channel": "delivery"}, actor=self.owner)
        self.assertEqual(error.exception.code, "no_open_shift")

    def test_assign_table_checks_role_activity_and_membership(self):
        self.authenticate(self.owner.user)
        shift = self.create_shift()
        for employee in (self.chef, self.inactive, self.waiter):
            shift.employees.create(employee=employee)
        cases = [
            (self.table, self.chef, "invalid_waiter_role"),
            (self.table, self.other_waiter, "waiter_not_in_shift"),
            (self.table, self.inactive, "inactive_employee"),
            (self.inactive_table, self.waiter, "inactive_table"),
        ]
        for table, employee, code in cases:
            with self.subTest(code=code):
                response = self.client.put(
                    self.assignment_url(shift.pk, table.pk),
                    {"waiter_id": employee.pk},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], code)
        self.assertFalse(ShiftTableAssignment.objects.exists())

    def test_table_list_is_scoped_to_current_shift_and_waiter(self):
        shift = self.create_shift()
        closed = RestaurantShift.objects.create(status=RestaurantShift.Status.CLOSED)
        for assignment_shift, table, waiter in (
            (shift, self.table, self.waiter),
            (shift, self.other_table, self.other_waiter),
            (closed, self.other_table, self.waiter),
        ):
            assignment_shift.employees.create(employee=waiter)
            ShiftTableAssignment.objects.create(shift=assignment_shift, table=table, waiter=waiter)

        self.authenticate(self.waiter.user)
        response = self.client.get(self.tables_url, {"waiter_id": self.other_waiter.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["table"] for item in response.data], [self.table.pk])
        self.authenticate(self.administrator.user)
        response = self.client.get(self.tables_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["table"] for item in response.data], [self.table.pk, self.other_table.pk]
        )

    def test_jwt_and_roles_are_required(self):
        shift = self.create_shift()
        management_requests = [
            ("post", self.open_url),
            ("post", reverse("operations:shift-close", args=[shift.pk])),
            ("get", self.employees_url(shift.pk)),
            ("post", self.employees_url(shift.pk)),
            ("put", self.assignment_url(shift.pk, self.table.pk)),
        ]
        for method, url in [
            *management_requests, ("get", self.current_url), ("get", self.tables_url)
        ]:
            with self.subTest(method=method, url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 401)

        for employee in (self.waiter, self.chef):
            self.authenticate(employee.user)
            self.assertEqual(self.client.get(self.current_url).status_code, 200)
            for method, url in management_requests:
                with self.subTest(role=employee.role, method=method, url=url):
                    self.assertEqual(getattr(self.client, method)(url).status_code, 403)
        self.assertEqual(self.client.get(self.tables_url).status_code, 403)

        user_without_profile = get_user_model().objects.create_user(username="no_profile")
        self.authenticate(user_without_profile)
        self.assertEqual(self.client.get(self.current_url).status_code, 403)
        self.authenticate(self.waiter.user)
        self.waiter.user.is_active = False
        self.waiter.user.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.current_url).status_code, 401)

    def test_closed_shift_rejects_members_and_assignments(self):
        self.authenticate(self.owner.user)
        shift = RestaurantShift.objects.create(status=RestaurantShift.Status.CLOSED)
        member = self.client.post(
            self.employees_url(shift.pk), {"employee_id": self.waiter.pk}, format="json"
        )
        assignment = self.client.put(
            self.assignment_url(shift.pk, self.table.pk),
            {"waiter_id": self.waiter.pk},
            format="json",
        )
        for response in (member, assignment):
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "shift_closed")

    def test_missing_objects_and_invalid_employee_id(self):
        self.authenticate(self.owner.user)
        shift = self.create_shift()
        self.assertEqual(self.client.get(self.employees_url(shift.pk + 1)).status_code, 404)
        self.assertEqual(
            self.client.post(reverse("operations:shift-close", args=[shift.pk + 1])).status_code,
            404,
        )
        missing_employee = self.client.post(
            self.employees_url(shift.pk), {"employee_id": 999999}, format="json"
        )
        missing_table = self.client.put(
            self.assignment_url(shift.pk, 999999), {"waiter_id": self.waiter.pk},
            format="json",
        )
        invalid_employee = self.client.post(
            self.employees_url(shift.pk), {"employee_id": 0}, format="json"
        )
        self.assertEqual(missing_employee.status_code, 404)
        self.assertEqual(missing_table.status_code, 404)
        self.assertEqual(invalid_employee.status_code, 400)

    def test_database_constraints(self):
        shift = self.create_shift()
        shift.employees.create(employee=self.waiter)
        ShiftTableAssignment.objects.create(shift=shift, table=self.table, waiter=self.waiter)
        with self.assertRaises(IntegrityError), transaction.atomic():
            RestaurantShift.objects.create()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShiftEmployee.objects.create(shift=shift, employee=self.waiter)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShiftTableAssignment.objects.create(
                shift=shift, table=self.table, waiter=self.other_waiter
            )


class SalesReportAPITests(APITestCase):
    period = {"date_from": "2026-05-03", "date_to": "2026-05-04"}
    names = ("sales-summary", "popular-dishes", "sales-channels", "sales-compare", "sales-csv")

    @classmethod
    def setUpTestData(cls):
        cls.owner = create_employee("owner", EmployeeProfile.Role.OWNER)
        cls.waiter = create_employee("waiter", EmployeeProfile.Role.WAITER)
        cls.chef = create_employee("chef", EmployeeProfile.Role.CHEF)
        cls.shift = RestaurantShift.objects.create(opened_by=cls.owner)
        category = Category.objects.create(name="Горячее", slug="hot")
        cls.dish = Dish.objects.create(
            name="Стейк", slug="steak", category=category, price=Decimal("100.00")
        )

        # 18:00 UTC — начало следующего дня в Бишкеке.
        cls.first_order = cls.create_sale(datetime(2026, 5, 2, 18, tzinfo=UTC), quantity=2)
        cls.add_line(cls.first_order, price="100.00")
        cls.last_order = cls.create_sale(
            datetime(2026, 5, 4, 17, 59, 59, 999999, tzinfo=UTC),
            price="50.00",
            channel="takeaway",
            status="served",
        )
        cls.add_line(cls.last_order, price="25.00", dish_name="Стейк по-другому")
        cls.create_sale(datetime(2026, 4, 30, 18, tzinfo=UTC), price="200.00")
        cls.create_sale(datetime(2026, 5, 2, 17, 59, 59, tzinfo=UTC), price="50.00")
        cls.create_sale(datetime(2026, 4, 30, 17, 59, 59, tzinfo=UTC))
        cls.create_sale(datetime(2026, 5, 4, 18, tzinfo=UTC))
        cls.create_sale(datetime(2026, 5, 3, tzinfo=UTC), status="cancelled")
        cls.create_sale(datetime(2026, 5, 3, tzinfo=UTC), is_paid=False)

    @classmethod
    def add_line(cls, order, *, price, quantity=1, dish_name="Стейк"):
        OrderItem.objects.create(
            order=order, dish=cls.dish, dish_name=dish_name, unit_price=Decimal(price),
            quantity=quantity, station="hot",
        )

    @classmethod
    def create_sale(
        cls, paid_at, *, price="100.00", quantity=1, channel="dine_in",
        status="closed", is_paid=True,
    ):
        order = Order.objects.create(
            shift=cls.shift, channel=channel, status=status,
            paid_at=paid_at, is_paid=is_paid, payment_method="card",
        )
        cls.add_line(order, price=price, quantity=quantity)
        return order

    def setUp(self):
        self.authenticate(self.owner)

    def authenticate(self, employee):
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(employee.user)}"
        )

    def get_report(self, name, period, **kwargs):
        return self.client.get(reverse(f"operations:{name}"), period, **kwargs)

    def test_summary_counts_orders_and_uses_price_snapshots(self):
        Dish.objects.filter(pk=self.dish.pk).update(price=Decimal("999.00"))
        response = self.get_report("sales-summary", self.period)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"revenue": "375.00", "paid_orders_count": 2, "average_check": "187.50", "currency": "KGS"},
        )

    def test_popular_dishes_group_snapshots_and_channels_include_empty_channel(self):
        popular = self.get_report("popular-dishes", self.period)
        self.assertEqual(popular.status_code, 200)
        self.assertEqual(popular.json(), [
            {"dish_id": self.dish.pk, "dish_name": "Стейк", "quantity": 4},
            {"dish_id": self.dish.pk, "dish_name": "Стейк по-другому", "quantity": 1},
        ])
        channels = self.get_report("sales-channels", self.period)
        self.assertEqual(channels.status_code, 200)
        self.assertEqual(channels.json(), [
            {"channel": "dine_in", "paid_orders_count": 1, "revenue": "300.00"},
            {"channel": "takeaway", "paid_orders_count": 1, "revenue": "75.00"},
            {"channel": "delivery", "paid_orders_count": 0, "revenue": "0.00"},
        ])

    def test_compare_uses_previous_period_of_equal_length(self):
        response = self.get_report("sales-compare", self.period)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "current_revenue": "375.00",
            "previous_revenue": "250.00",
            "difference": "125.00",
            "percent_change": "50.00",
        })

    def test_local_date_default_empty_sales_and_invalid_periods(self):
        with patch("django.utils.timezone.now", return_value=datetime(2026, 5, 2, 20, tzinfo=UTC)):
            today = self.get_report("sales-summary", {})
        self.assertEqual(today.status_code, 200)
        self.assertEqual(today.json()["revenue"], "300.00")

        empty_period = {"date_from": "2026-05-20", "date_to": "2026-05-20"}
        empty = self.get_report("sales-summary", empty_period)
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json(), {
            "revenue": "0.00", "paid_orders_count": 0, "average_check": "0.00", "currency": "KGS",
        })
        comparison = self.get_report("sales-compare", empty_period)
        self.assertEqual(comparison.status_code, 200)
        self.assertIsNone(comparison.json()["percent_change"])

        for invalid in (
            {"date_from": ""},
            {"date_from": "2026-02-30"},
            {"date_from": "2026-5-03"},
            {"date_from": "2026-05-04", "date_to": "2026-05-03"},
            {"date_from": "2024-01-01", "date_to": "2025-01-01"},
            {"date_from": "0001-01-01", "date_to": "0001-01-01"},
        ):
            with self.subTest(period=invalid):
                self.assertEqual(self.get_report("sales-summary", invalid).status_code, 400)

    def test_csv_contains_only_sales_fields_and_rows(self):
        response = self.get_report("sales-csv", self.period, HTTP_ACCEPT="text/csv")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="sales.csv"')
        self.assertEqual(list(csv.reader(response.content.decode("utf-8").splitlines())), [
            ["order_number", "paid_at", "channel", "total", "payment_method"],
            [self.first_order.number, "2026-05-03T00:00:00+06:00", "dine_in", "300.00", "card"],
            [self.last_order.number, "2026-05-04T23:59:59.999999+06:00", "takeaway", "75.00", "card"],
        ])
        invalid = self.get_report("sales-csv", {"date_from": "bad"}, HTTP_ACCEPT="text/csv")
        self.assertEqual(invalid.status_code, 400)
        self.assertIn("date_from", invalid.json())

    def test_all_reports_require_manager_role_and_jwt(self):
        self.client.credentials()
        for name in self.names:
            with self.subTest(name=name):
                self.assertEqual(self.get_report(name, self.period).status_code, 401)
        for employee in (self.waiter, self.chef):
            self.authenticate(employee)
            for name in self.names:
                with self.subTest(name=name, role=employee.role):
                    self.assertEqual(self.get_report(name, self.period).status_code, 403)
