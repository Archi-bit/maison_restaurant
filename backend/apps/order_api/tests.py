from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from apps.catalog.models import Category, Dish
from apps.operations.models import RestaurantShift, ShiftTableAssignment
from apps.orders.models import Order
from apps.reservations.models import Reservation, RestaurantTable
from apps.staff.models import EmployeeProfile


API = "/api/v1/staff"
ORDERS = f"{API}/orders/"
WAITER_ORDERS = f"{API}/waiter/orders/"
KITCHEN = f"{API}/kitchen/orders/"
PASSWORD = "OrderApi-test-password"


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OrderApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = cls.create_employee("owner", "owner")
        cls.admin = cls.create_employee("admin", "administrator")
        cls.waiter = cls.create_employee("waiter", "waiter")
        cls.other_waiter = cls.create_employee("other-waiter", "waiter")
        cls.chef = cls.create_employee("chef", "chef")
        cls.shift = RestaurantShift.objects.create(opened_by=cls.owner)
        cls.table = RestaurantTable.objects.create(code="T05", capacity=4, zone="main")
        cls.other_table = RestaurantTable.objects.create(code="T06", capacity=4, zone="main")
        ShiftTableAssignment.objects.create(shift=cls.shift, table=cls.table, waiter=cls.waiter)
        ShiftTableAssignment.objects.create(
            shift=cls.shift, table=cls.other_table, waiter=cls.other_waiter
        )
        cls.reservation = cls.create_reservation(cls.table, cls.waiter)
        cls.other_reservation = cls.create_reservation(cls.other_table, cls.other_waiter)
        cls.hot_dish = Dish.objects.create(
            category=Category.objects.create(name="Горячее", slug="hot"),
            name="Стейк", price=Decimal("945.00"),
        )
        cls.cold_dish = Dish.objects.create(
            category=Category.objects.create(name="Салаты", slug="salads"),
            name="Салат", price=Decimal("450.00"),
        )

    @staticmethod
    def create_employee(username, role):
        user = get_user_model().objects.create_user(username=username, password=PASSWORD)
        return EmployeeProfile.objects.create(
            user=user, work_email=f"{username}@example.test", full_name=username, role=role,
        )

    @staticmethod
    def create_reservation(table, waiter):
        return Reservation.objects.create(
            guest_name="Тестовый гость", phone="+996700123456",
            date=timezone.localdate(), start_time=time(14), end_time=time(16),
            guests_count=2, status="arrived", source="phone",
            table=table, responsible_employee=waiter,
        )

    def authenticate(self, employee):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(employee.user)}")

    def create_order(self, reservation=None):
        payload = (
            {"channel": "dine_in", "reservation_id": reservation.pk}
            if reservation else {"channel": "takeaway"}
        )
        response = self.client.post(ORDERS, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return f"{ORDERS}{response.data['id']}/"

    def add_item(self, order_url, dish, quantity=2):
        response = self.client.post(
            f"{order_url}items/", {"dish_id": dish.pk, "quantity": quantity}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def action(self, url, payload=None):
        return self.client.post(url, payload if payload is not None else {}, format="json")

    def assert_business_error(self, response, code):
        self.assertEqual(response.status_code, 400, response.data)
        self.assertEqual(response.data["code"], code)
        self.assertTrue(response.data["detail"])

    def test_jwt_and_employee_required(self):
        complete = f"{API}/reservations/{self.reservation.pk}/complete/"
        for url in (ORDERS, WAITER_ORDERS, KITCHEN):
            self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.action(complete).status_code, 401)
        no_profile = get_user_model().objects.create_user(username="guest")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {AccessToken.for_user(no_profile)}")
        self.assertEqual(self.client.get(ORDERS).status_code, 403)
        self.authenticate(self.owner)
        get_user_model().objects.filter(pk=self.owner.user_id).update(is_active=False)
        self.assertEqual(self.client.get(ORDERS).status_code, 401)

    def test_waiter_orders_and_table_scope(self):
        self.authenticate(self.admin)
        own = self.create_order(self.reservation)
        foreign = self.create_order(self.other_reservation)
        self.assertEqual(self.client.get(ORDERS).data["count"], 2)
        self.assertEqual(self.client.get(WAITER_ORDERS).status_code, 403)

        self.authenticate(self.waiter)
        for url in (ORDERS, WAITER_ORDERS):
            response = self.client.get(url, {"status": "draft", "page": 1})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["count"], 1)
            self.assertEqual(response.data["results"][0]["table_id"], self.table.pk)
        self.assertEqual(self.client.get(own).status_code, 200)
        self.assertEqual(self.client.get(foreign).status_code, 404)
        self.assertEqual(self.action(f"{foreign}send/").status_code, 404)
        self.assertEqual(self.action(f"{own}cancel/", {"reason": "Тест"}).status_code, 403)
        self.assertEqual(self.action(ORDERS, {"channel": "takeaway"}).status_code, 403)
        self.assertEqual(self.action(ORDERS, {
            "channel": "dine_in", "reservation_id": self.other_reservation.pk,
        }).status_code, 403)

    def test_waiter_can_create_order_for_assigned_table(self):
        self.authenticate(self.waiter)
        own = self.create_order(self.reservation)
        response = self.client.get(own).data
        self.assertEqual(response["table_code"], self.table.code)
        self.assertEqual(response["waiter"]["id"], self.waiter.pk)
        self.assertEqual(response["created_by_id"], self.waiter.pk)
        self.assertEqual(response["shift_id"], self.shift.pk)
        self.assertEqual(response["total"], "0.00")

    def test_create_without_open_shift(self):
        RestaurantShift.objects.filter(pk=self.shift.pk).update(
            status=RestaurantShift.Status.CLOSED
        )
        payload = {"channel": "dine_in", "reservation_id": self.reservation.pk}
        self.authenticate(self.waiter)
        self.assertEqual(self.action(ORDERS, payload).status_code, 403)
        self.authenticate(self.owner)
        self.assert_business_error(self.action(ORDERS, payload), "no_open_shift")
        self.assertFalse(Order.objects.exists())

    def test_write_serializers_reject_unexpected_fields(self):
        self.authenticate(self.owner)
        forbidden = dict.fromkeys(
            ("status", "created_by", "waiter", "shift", "table", "is_paid", "total"), 1
        )
        response = self.action(ORDERS, {"channel": "delivery", **forbidden})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.data), set(forbidden))
        self.assertFalse(Order.objects.exists())
        for channel, reservation_id in (("dine_in", None), ("takeaway", self.reservation.pk)):
            payload = {"channel": channel}
            if reservation_id is not None:
                payload["reservation_id"] = reservation_id
            self.assertEqual(self.action(ORDERS, payload).status_code, 400)

        url = self.create_order()
        response = self.action(f"{url}items/", {
            "dish_id": self.hot_dish.pk, "quantity": 1, "unit_price": "0.01",
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn("unit_price", response.data)
        self.assertEqual(self.client.patch(url, {"is_paid": True}, format="json").status_code, 405)
        self.assertEqual(self.action(f"{url}pay/", {
            "method": "card", "amount": "0.01", "card_number": "123",
        }).status_code, 400)
        self.assertEqual(self.client.get(url).data["items"], [])
        self.assertFalse(self.client.get(url).data["is_paid"])

    def test_draft_item_edit_removal_and_order_ownership(self):
        self.authenticate(self.owner)
        url = self.create_order()
        foreign_url = self.create_order()
        item = self.add_item(url, self.hot_dish)["items"][0]
        self.assertEqual((item["unit_price"], item["line_total"]), ("945.00", "1890.00"))
        item_url = f"{url}items/{item['id']}/"
        wrong_url = f"{foreign_url}items/{item['id']}/"
        self.assertEqual(self.client.delete(wrong_url).status_code, 404)
        self.assertEqual(self.client.patch(wrong_url, {"quantity": 1}, format="json").status_code, 404)
        self.assertEqual(self.client.patch(item_url, {"quantity": 0}, format="json").status_code, 400)
        response = self.client.patch(item_url, {"note": "Без орехов"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["items"][0]["quantity"], 2)
        self.assertEqual(response.data["items"][0]["note"], "Без орехов")
        response = self.client.delete(item_url)
        self.assertEqual((response.status_code, response.content), (204, b""))
        self.assertEqual(self.client.get(url).data["total"], "0.00")

    def test_lifecycle_and_complete_visit(self):
        login = self.action(f"{API}/auth/login/", {
            "work_email": self.owner.work_email, "password": PASSWORD,
        })
        self.assertEqual(login.status_code, 200, login.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get(f"{API}/auth/me/").data["role"], "owner")
        url = self.create_order(self.reservation)
        self.assert_business_error(self.action(f"{url}send/"), "empty_order")
        added = self.add_item(url, self.hot_dish)
        self.assertEqual((added["subtotal"], added["total"], added["currency"]), (
            "1890.00", "1890.00", "KGS",
        ))
        self.assertTrue(added["created_at"].endswith("+06:00"))
        item_url = f"{url}items/{added['items'][0]['id']}/"
        self.assertEqual(self.action(f"{url}send/").data["status"], "new")
        self.assert_business_error(
            self.client.patch(item_url, {"quantity": 3}, format="json"), "invalid_status"
        )
        self.assert_business_error(self.client.delete(item_url), "invalid_status")

        self.authenticate(self.waiter)
        complete = f"{API}/reservations/{self.reservation.pk}/complete/"
        self.assert_business_error(self.action(complete), "active_order")
        self.assertEqual(self.action(f"{url}preparing/").status_code, 403)
        self.assertEqual(self.action(f"{url}ready/").status_code, 403)
        self.assertEqual(
            self.action(f"{API}/reservations/{self.other_reservation.pk}/complete/").status_code,
            404,
        )

        self.authenticate(self.chef)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.get(ORDERS).status_code, 403)
        self.assertEqual(self.client.get(f"{API}/reservations/").status_code, 403)
        self.assertEqual(self.action(complete).status_code, 403)
        self.assertEqual(self.action(f"{url}pay/", {"method": "cash"}).status_code, 403)
        for action, expected in (("preparing", "preparing"), ("ready", "ready")):
            response = self.action(f"{url}{action}/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data["status"], expected)
            self.assertEqual(set(response.data), {
                "id", "number", "table_code", "channel", "created_at", "status", "items",
            })
        self.assert_business_error(self.action(f"{url}ready/"), "invalid_status")

        self.authenticate(self.waiter)
        self.assertEqual(self.action(f"{url}serve/").data["status"], "served")
        self.assert_business_error(self.action(f"{url}close/"), "payment_required")
        paid = self.action(f"{url}pay/", {"method": "cash"})
        self.assertEqual(paid.status_code, 200)
        self.assertTrue(paid.data["is_paid"])
        self.assertEqual(paid.data["payment_method"], "cash")
        self.assert_business_error(self.action(f"{url}pay/", {"method": "cash"}), "already_paid")
        closed = self.action(f"{url}close/")
        self.assertEqual(closed.data["status"], "closed")
        self.assertEqual([event["action"] for event in closed.data["history"]], [
            "created", "item_added", "sent_to_kitchen", "preparing", "ready", "served",
            "paid", "closed",
        ])
        response = self.action(complete)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "completed")
        self.assertEqual(response.data["history"][-1]["action"], "completed")
        self.assert_business_error(self.action(complete), "invalid_status")

        self.authenticate(self.owner)
        reservations = self.client.get(f"{API}/reservations/", {"status": "completed"})
        self.assertEqual(reservations.data["count"], 1)
        sales = self.client.get(f"{API}/reports/summary/")
        self.assertEqual(sales.data["paid_orders_count"], 1)
        self.assertEqual(sales.data["revenue"], "1890.00")

    def test_order_filters_and_pagination(self):
        self.authenticate(self.owner)
        self.create_order(self.reservation)
        Order.objects.bulk_create([
            Order(channel="delivery", shift=self.shift) for _ in range(21)
        ])
        response = self.client.get(ORDERS, {"channel": "delivery", "page": 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 21)
        self.assertEqual(len(response.data["results"]), 1)
        self.assertIsNone(response.data["next"])
        self.assertIn("channel=delivery", response.data["previous"])
        response = self.client.get(ORDERS, {
            "status": "draft", "table_id": self.table.pk, "date": timezone.localdate(),
        })
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(self.client.get(ORDERS, {"date": "invalid"}).status_code, 400)

    def test_kitchen_filters_privacy_and_empty_page(self):
        self.authenticate(self.owner)
        url = self.create_order(self.reservation)
        self.add_item(url, self.hot_dish)
        self.add_item(url, self.hot_dish, quantity=1)
        self.add_item(url, self.cold_dish)
        self.assertEqual(self.action(f"{url}send/").status_code, 200)
        self.authenticate(self.waiter)
        self.assertEqual(self.client.get(KITCHEN).status_code, 403)
        self.authenticate(self.chef)
        response = self.client.get(KITCHEN, {"station": "hot", "status": "new", "page": 1})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        ticket = response.data["results"][0]
        self.assertEqual(ticket["table_code"], self.table.code)
        self.assertEqual(len(ticket["items"]), 2)
        for item in ticket["items"]:
            self.assertEqual(set(item), {"dish_name", "quantity", "station", "note"})
            self.assertEqual(item["station"], "hot")
        self.assertEqual(
            self.client.get(KITCHEN, {"station": "cold", "status": "preparing"}).data["results"],
            [],
        )
        for params in ({"status": "closed"}, {"station": "invalid"}):
            self.assertEqual(self.client.get(KITCHEN, params).status_code, 400)

    def test_cancel_requires_manager_and_reason(self):
        self.authenticate(self.admin)
        url = self.create_order()
        for payload in ({}, {"reason": "  "}, {"reason": 123}):
            self.assertEqual(self.action(f"{url}cancel/", payload).status_code, 400)
        cancelled = self.action(f"{url}cancel/", {"reason": "Гость отказался"})
        self.assertEqual(cancelled.data["status"], "cancelled")
        self.assertIn("Гость отказался", cancelled.data["history"][-1]["details"])
        self.assert_business_error(
            self.action(f"{url}cancel/", {"reason": "Повтор"}), "invalid_status"
        )
