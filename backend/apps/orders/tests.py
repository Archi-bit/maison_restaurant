from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.catalog.models import Category, Dish
from apps.staff.models import EmployeeProfile
from apps.reservations.models import Reservation, RestaurantTable
from apps.reservations.services import complete_visit, get_hall_plan, ReservationBusinessError
from apps.operations.models import RestaurantShift, ShiftTableAssignment
from .models import Order, OrderItem, OrderHistory
from .services import (
    OrderBusinessError,
    create_order,
    add_order_item,
    update_order_item,
    remove_order_item,
    send_to_kitchen,
    start_preparing,
    mark_ready,
    mark_served,
    mark_paid,
    close_order,
    cancel_order,
)

User = get_user_model()


class OrdersTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Пользователи
        cls.user_owner = User.objects.create_user(username="owner", password="pass")
        cls.user_admin = User.objects.create_user(username="admin", password="pass")
        cls.user_waiter = User.objects.create_user(username="waiter", password="pass")
        cls.user_chef = User.objects.create_user(username="chef", password="pass")

        # Профили
        cls.owner = EmployeeProfile.objects.create(
            user=cls.user_owner,
            work_email="owner@test.com",
            full_name="Владелец",
            role="owner",
        )
        cls.admin = EmployeeProfile.objects.create(
            user=cls.user_admin,
            work_email="admin@test.com",
            full_name="Администратор",
            role="administrator",
        )
        cls.waiter = EmployeeProfile.objects.create(
            user=cls.user_waiter,
            work_email="waiter@test.com",
            full_name="Официант",
            role="waiter",
        )
        cls.chef = EmployeeProfile.objects.create(
            user=cls.user_chef,
            work_email="chef@test.com",
            full_name="Повар",
            role="chef",
        )

        # Категории и блюда
        cls.cat_hot = Category.objects.create(name="Горячее", slug="hot", is_active=True)
        cls.cat_cold = Category.objects.create(name="Салаты", slug="salads", is_active=True)

        cls.dish_hot = Dish.objects.create(
            name="Стейк",
            slug="steak",
            price=Decimal("1890.00"),
            category=cls.cat_hot,
            is_active=True,
            is_available=True,
        )
        cls.dish_cold = Dish.objects.create(
            name="Цезарь",
            slug="caesar",
            price=Decimal("980.00"),
            category=cls.cat_cold,
            is_active=True,
            is_available=True,
        )

        # Стол
        cls.table = RestaurantTable.objects.create(
            code="T05", capacity=4, zone="main", is_active=True
        )

    def setUp(self):
        # Открытая смена
        self.shift = RestaurantShift.objects.create(
            status="open", opened_by=self.owner
        )
        # Назначение официанта на стол
        self.assignment = ShiftTableAssignment.objects.create(
            shift=self.shift, table=self.table, waiter=self.waiter
        )
        # Бронирование (в рабочие часы ресторана: 12:00-23:00)
        from datetime import time as d_time
        self.reservation = Reservation.objects.create(
            guest_name="Иван Иванов",
            phone="+996700123456",
            date=timezone.now().date(),
            start_time=d_time(14, 0),
            end_time=d_time(16, 0),
            guests_count=2,
            status="arrived",
            source="phone",
            table=self.table,
            created_by=self.admin,
        )

    def test_create_dine_in(self):
        """Создание заказа dine_in с бронированием."""
        order = create_order(
            validated_data={
                "channel": "dine_in",
                "reservation_id": self.reservation.pk,
                "note": "Без лука",
            },
            actor=self.waiter,
        )
        self.assertEqual(order.status, "draft")
        self.assertEqual(order.channel, "dine_in")
        self.assertEqual(order.table, self.table)
        self.assertEqual(order.waiter, self.waiter)
        self.assertEqual(order.shift, self.shift)
        self.assertEqual(order.reservation, self.reservation)
        self.assertFalse(order.is_paid)

        # Проверка истории
        history = OrderHistory.objects.filter(order=order, action="created")
        self.assertTrue(history.exists())

    def test_without_shift(self):
        """Попытка создать заказ без открытой смены."""
        self.shift.status = "closed"
        self.shift.save()

        with self.assertRaises(OrderBusinessError) as ctx:
            create_order(
                validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
                actor=self.waiter,
            )
        self.assertEqual(ctx.exception.code, "no_open_shift")

    def test_duplicate_reservation(self):
        """Дублирование заказа для одной брони."""
        create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        with self.assertRaises(OrderBusinessError) as ctx:
            create_order(
                validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
                actor=self.waiter,
            )
        self.assertEqual(ctx.exception.code, "duplicate_reservation")

    def test_historical_price(self):
        """Snapshot цены: изменение цены блюда не влияет на позицию."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        item = add_order_item(
            order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter
        )
        self.assertEqual(item.unit_price, Decimal("1890.00"))

        # Меняем цену блюда
        self.dish_hot.price = Decimal("1990.00")
        self.dish_hot.save()

        # Перечитываем позицию
        item.refresh_from_db()
        self.assertEqual(item.unit_price, Decimal("1890.00"))

    def test_quantity_edges(self):
        """Граничные значения quantity."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )

        # 0
        with self.assertRaises(OrderBusinessError) as ctx:
            add_order_item(order=order, dish=self.dish_hot, quantity=0, note="", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_quantity")

        # 100
        with self.assertRaises(OrderBusinessError) as ctx:
            add_order_item(order=order, dish=self.dish_hot, quantity=100, note="", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_quantity")

        # 1.5
        with self.assertRaises(OrderBusinessError) as ctx:
            add_order_item(order=order, dish=self.dish_hot, quantity=1.5, note="", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_quantity")

        # True (bool)
        with self.assertRaises(OrderBusinessError) as ctx:
            add_order_item(order=order, dish=self.dish_hot, quantity=True, note="", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_quantity")

    def test_empty_kitchen(self):
        """Отправка пустого заказа на кухню."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        with self.assertRaises(OrderBusinessError) as ctx:
            send_to_kitchen(order=order, actor=self.waiter)
        self.assertEqual(ctx.exception.code, "empty_order")

    def test_edit_after_send(self):
        """Запрет редактирования и удаления позиций после отправки на кухню."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        item = add_order_item(
            order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter
        )
        send_to_kitchen(order=order, actor=self.waiter)

        # Попытка изменить
        with self.assertRaises(OrderBusinessError) as ctx:
            update_order_item(item=item, quantity=2, actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_status")

        # Попытка удалить
        with self.assertRaises(OrderBusinessError) as ctx:
            remove_order_item(item=item, actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_status")

    def test_ordered_transitions(self):
        """Правильные переходы статусов: new → preparing → ready → served."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)

        send_to_kitchen(order=order, actor=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, "new")

        start_preparing(order=order, actor=self.chef)
        order.refresh_from_db()
        self.assertEqual(order.status, "preparing")

        mark_ready(order=order, actor=self.chef)
        order.refresh_from_db()
        self.assertEqual(order.status, "ready")

        mark_served(order=order, actor=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, "served")

        # Проверка истории: 5 записей (created, item_added, sent_to_kitchen, preparing, ready, served)
        history_count = OrderHistory.objects.filter(order=order).count()
        self.assertEqual(history_count, 6)

    def test_invalid_transition(self):
        """Неверный переход статусов."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)
        send_to_kitchen(order=order, actor=self.waiter)
        start_preparing(order=order, actor=self.chef)
        mark_ready(order=order, actor=self.chef)

        # Повторный ready
        with self.assertRaises(OrderBusinessError) as ctx:
            mark_ready(order=order, actor=self.chef)
        self.assertEqual(ctx.exception.code, "invalid_status")

        # served из new (пропуская preparing и ready)
        order2 = create_order(
            validated_data={"channel": "takeaway"},
            actor=self.admin,
        )
        add_order_item(order=order2, dish=self.dish_cold, quantity=1, note="", actor=self.admin)
        send_to_kitchen(order=order2, actor=self.admin)

        with self.assertRaises(OrderBusinessError) as ctx:
            mark_served(order=order2, actor=self.waiter)
        self.assertEqual(ctx.exception.code, "invalid_status")

    def test_payment_once(self):
        """Оплата возможна только один раз."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)
        send_to_kitchen(order=order, actor=self.waiter)
        start_preparing(order=order, actor=self.chef)
        mark_ready(order=order, actor=self.chef)
        mark_served(order=order, actor=self.waiter)

        mark_paid(order=order, payment_method="cash", actor=self.waiter)
        order.refresh_from_db()
        self.assertTrue(order.is_paid)

        # Повторная оплата
        with self.assertRaises(OrderBusinessError) as ctx:
            mark_paid(order=order, payment_method="card", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "already_paid")

    def test_close_paid(self):
        """Закрытие только после оплаты."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)
        send_to_kitchen(order=order, actor=self.waiter)
        start_preparing(order=order, actor=self.chef)
        mark_ready(order=order, actor=self.chef)
        mark_served(order=order, actor=self.waiter)

        # Без оплаты
        with self.assertRaises(OrderBusinessError) as ctx:
            close_order(order=order, actor=self.waiter)
        self.assertEqual(ctx.exception.code, "payment_required")

        # После оплаты
        mark_paid(order=order, payment_method="cash", actor=self.waiter)
        close_order(order=order, actor=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, "closed")
        self.assertIsNotNone(order.closed_at)

    def test_complete_visit(self):
        """Завершение визита после закрытия заказа."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)
        send_to_kitchen(order=order, actor=self.waiter)
        start_preparing(order=order, actor=self.chef)
        mark_ready(order=order, actor=self.chef)
        mark_served(order=order, actor=self.waiter)
        mark_paid(order=order, payment_method="cash", actor=self.waiter)

        # Попытка завершить визит с активным заказом (served)
        with self.assertRaises(ReservationBusinessError) as ctx:
            complete_visit(reservation=self.reservation, actor=self.admin)
        self.assertEqual(ctx.exception.code, "active_order")

        # После закрытия заказа
        close_order(order=order, actor=self.waiter)
        reservation = complete_visit(reservation=self.reservation, actor=self.admin)
        self.assertEqual(reservation.status, "completed")

    def test_get_hall_plan_after_completed(self):
        """План зала: completed не занимает стол."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)
        send_to_kitchen(order=order, actor=self.waiter)
        start_preparing(order=order, actor=self.chef)
        mark_ready(order=order, actor=self.chef)
        mark_served(order=order, actor=self.waiter)
        mark_paid(order=order, payment_method="cash", actor=self.waiter)
        close_order(order=order, actor=self.waiter)
        complete_visit(reservation=self.reservation, actor=self.admin)

        hall_plan = get_hall_plan(date=self.reservation.date, time=self.reservation.start_time)
        table_status = next((t for t in hall_plan["tables"] if t["code"] == "T05"), None)
        self.assertIsNotNone(table_status)
        self.assertEqual(table_status["status"], "free")

    def test_takeaway_no_reservation(self):
        """Takeaway без брони."""
        order = create_order(
            validated_data={"channel": "takeaway", "note": "Звонил заранее"},
            actor=self.admin,
        )
        self.assertEqual(order.channel, "takeaway")
        self.assertIsNone(order.reservation)
        self.assertIsNone(order.table)
        self.assertIsNone(order.waiter)

    def test_total_calculation(self):
        """Расчёт total."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=2, note="", actor=self.waiter)
        add_order_item(order=order, dish=self.dish_cold, quantity=1, note="", actor=self.waiter)

        # 2 × 1890.00 + 1 × 980.00 = 4760.00
        self.assertEqual(order.total, Decimal("4760.00"))

    def test_cancel_order(self):
        """Отмена заказа."""
        order = create_order(
            validated_data={"channel": "dine_in", "reservation_id": self.reservation.pk},
            actor=self.waiter,
        )
        add_order_item(order=order, dish=self.dish_hot, quantity=1, note="", actor=self.waiter)

        # Причина обязательна
        with self.assertRaises(OrderBusinessError) as ctx:
            cancel_order(order=order, reason="", actor=self.waiter)
        self.assertEqual(ctx.exception.code, "missing_reason")

        # Отмена draft
        cancel_order(order=order, reason="Гость передумал", actor=self.waiter)
        order.refresh_from_db()
        self.assertEqual(order.status, "cancelled")

        # Отмена оплаченного (в статусе new, но уже оплачен — не реалистично, но тестируем логику)
        order2 = create_order(
            validated_data={"channel": "takeaway"},
            actor=self.admin,
        )
        add_order_item(order=order2, dish=self.dish_cold, quantity=1, note="", actor=self.admin)
        send_to_kitchen(order=order2, actor=self.admin)
        
        # Принудительно установим is_paid=True в статусе new (для теста)
        order2.is_paid = True
        order2.save()

        with self.assertRaises(OrderBusinessError) as ctx:
            cancel_order(order=order2, reason="Ошибка", actor=self.admin)
        self.assertEqual(ctx.exception.code, "already_paid")
