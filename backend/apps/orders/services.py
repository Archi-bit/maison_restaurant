from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Dish
from apps.operations.models import RestaurantShift, ShiftTableAssignment
from apps.reservations.models import Reservation
from apps.staff.models import EmployeeProfile

from .models import Order, OrderHistory, OrderItem


class OrderBusinessError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _validate_actor(actor):
    """Проверка, что actor существует, связан с активным User и роль допустима."""
    if not isinstance(actor, EmployeeProfile):
        raise OrderBusinessError("invalid_actor", "Actor должен быть EmployeeProfile.")
    if not actor.user or not actor.user.is_active:
        raise OrderBusinessError("inactive_user", "Пользователь неактивен.")
    if actor.role not in ("owner", "administrator", "waiter", "chef"):
        raise OrderBusinessError("invalid_role", "Недопустимая роль сотрудника.")


def _get_open_shift():
    """Получить текущую открытую смену."""
    try:
        return RestaurantShift.objects.get(status="open")
    except RestaurantShift.DoesNotExist:
        raise OrderBusinessError("no_open_shift", "Нет открытой смены.") from None


def _lock_order(order_id):
    try:
        return Order.objects.select_for_update().get(pk=order_id)
    except Order.DoesNotExist:
        raise OrderBusinessError("order_not_found", "Заказ не найден.") from None


def _lock_order_item(order, item_id):
    try:
        return order.items.select_for_update().get(pk=item_id)
    except OrderItem.DoesNotExist:
        raise OrderBusinessError(
            "item_not_found", "Позиция не найдена в этом заказе."
        ) from None


@transaction.atomic
def create_order(*, validated_data, actor):
    """
    Создать заказ в статусе draft.

    validated_data: dict с ключами channel, reservation_id (опц.), note (опц.)
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    shift = _get_open_shift()

    channel = validated_data.get("channel")
    if channel not in ("dine_in", "takeaway", "delivery"):
        raise OrderBusinessError("invalid_channel", "Канал должен быть dine_in/takeaway/delivery.")

    reservation_id = validated_data.get("reservation_id")
    note = validated_data.get("note", "")
    reservation = None
    table = None
    waiter = None

    if channel == "dine_in":
        if not reservation_id:
            raise OrderBusinessError("reservation_required", "Для dine_in требуется reservation_id.")

        try:
            reservation = Reservation.objects.select_for_update().get(pk=reservation_id)
        except Reservation.DoesNotExist:
            raise OrderBusinessError("reservation_not_found", "Бронирование не найдено.") from None

        if reservation.status != "arrived":
            raise OrderBusinessError("reservation_not_arrived", "Гость еще не прибыл (статус не arrived).")

        table = reservation.table
        if table is None:
            raise OrderBusinessError("table_unassigned", "У брони нет назначенного стола.")
        if not table.is_active:
            raise OrderBusinessError("table_inactive", "Стол неактивен.")

        # Проверка дубликата заказа для этой брони
        if Order.objects.filter(reservation=reservation).exists():
            raise OrderBusinessError("duplicate_reservation", "Для этой брони уже существует заказ.")

        # Найти назначение официанта на этот стол
        try:
            assignment = ShiftTableAssignment.objects.select_for_update().get(shift=shift, table=table)
            waiter = assignment.waiter
        except ShiftTableAssignment.DoesNotExist:
            raise OrderBusinessError("table_unassigned", "Стол не назначен официанту в текущей смене.") from None

        # Проверка прав: если actor — waiter, должен быть назначен на этот стол
        if actor.role == "waiter" and actor != waiter:
            raise OrderBusinessError("access_denied", "Вы не можете создать заказ для стола, не назначенного вам.")

    else:
        # takeaway или delivery
        if reservation_id:
            raise OrderBusinessError("invalid_field", "Для takeaway/delivery нельзя указывать reservation_id.")
        if actor.role not in ("owner", "administrator"):
            raise OrderBusinessError("access_denied", "Только owner/admin могут создавать takeaway/delivery заказы.")

    # Создание заказа
    order = Order.objects.create(
        shift=shift,
        channel=channel,
        reservation=reservation,
        table=table,
        created_by=actor,
        waiter=waiter,
        status="draft",
        note=note,
        is_paid=False,
    )

    # История
    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="created",
        old_status="",
        new_status="draft",
        details=f"Заказ создан сотрудником {actor.full_name}",
    )

    return order


@transaction.atomic
def add_order_item(*, order, dish, quantity, note, actor) -> Order:
    """
    Добавить позицию в заказ (только draft).

    order: Order
    dish: Dish или pk
    quantity: int (1-99)
    note: str
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "draft":
        raise OrderBusinessError("invalid_status", "Добавление позиций возможно только в статусе draft.")

    # Проверка quantity
    if type(quantity) is not int or quantity < 1 or quantity > 99:
        raise OrderBusinessError("invalid_quantity", "Количество должно быть целым числом от 1 до 99.")

    # Проверка note
    if note and len(note) > 255:
        raise OrderBusinessError("invalid_note", "Примечание не должно превышать 255 символов.")

    dish_id = dish if isinstance(dish, int) else dish.pk
    try:
        dish = (
            Dish.objects.select_related("category")
            .select_for_update(of=("self",))
            .get(pk=dish_id)
        )
    except Dish.DoesNotExist:
        raise OrderBusinessError("dish_not_found", "Блюдо не найдено.") from None

    # Проверка доступности
    if not dish.is_active or not dish.is_available or not dish.category.is_active:
        raise OrderBusinessError("dish_unavailable", "Блюдо недоступно для заказа.")

    # Snapshot
    dish_name = dish.name
    unit_price = dish.price

    # Определение station
    station = "hot" if dish.category.slug == "hot" else "cold"

    # Создание позиции
    OrderItem.objects.create(
        order=order,
        dish=dish,
        dish_name=dish_name,
        unit_price=unit_price,
        quantity=quantity,
        note=note or "",
        station=station,
    )

    # История
    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="item_added",
        old_status="draft",
        new_status="draft",
        details=f"Добавлено: {dish_name} x{quantity}",
    )

    return order


@transaction.atomic
def update_order_item(*, item, quantity=None, note=None, actor) -> Order:
    """
    Обновить позицию заказа (только draft).

    item: OrderItem
    quantity: int или None
    note: str или None
    actor: EmployeeProfile
    """
    _validate_actor(actor)

    order = _lock_order(item.order_id)
    if order.status != "draft":
        raise OrderBusinessError("invalid_status", "Изменение позиций возможно только в статусе draft.")

    item = _lock_order_item(order, item.pk)

    if quantity is None and note is None:
        raise OrderBusinessError("empty_update", "Не указано ни одно поле для обновления.")

    changes = []

    if quantity is not None:
        if type(quantity) is not int or quantity < 1 or quantity > 99:
            raise OrderBusinessError("invalid_quantity", "Количество должно быть целым числом от 1 до 99.")
        item.quantity = quantity
        changes.append(f"количество={quantity}")

    if note is not None:
        if len(note) > 255:
            raise OrderBusinessError("invalid_note", "Примечание не должно превышать 255 символов.")
        item.note = note
        changes.append("примечание обновлено")

    item.save(update_fields=["quantity", "note"])

    # История
    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="item_updated",
        old_status="draft",
        new_status="draft",
        details=f"Изменено: {item.dish_name} ({', '.join(changes)})",
    )

    return order


@transaction.atomic
def remove_order_item(*, item, actor) -> Order:
    """
    Удалить позицию из заказа (только draft).

    item: OrderItem
    actor: EmployeeProfile
    """
    _validate_actor(actor)

    order = _lock_order(item.order_id)
    if order.status != "draft":
        raise OrderBusinessError("invalid_status", "Удаление позиций возможно только в статусе draft.")

    item = _lock_order_item(order, item.pk)
    dish_name = item.dish_name
    item.delete()

    # История
    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="item_removed",
        old_status="draft",
        new_status="draft",
        details=f"Удалено: {dish_name}",
    )

    return order


@transaction.atomic
def send_to_kitchen(*, order, actor):
    """
    Отправить заказ на кухню: draft → new.

    order: Order
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "draft":
        raise OrderBusinessError("invalid_status", "Отправить на кухню можно только заказ в статусе draft.")

    # Проверка наличия позиций
    if not order.items.exists():
        raise OrderBusinessError("empty_order", "Нельзя отправить пустой заказ на кухню.")

    order.status = "new"
    order.save(update_fields=["status", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="sent_to_kitchen",
        old_status="draft",
        new_status="new",
        details=f"Заказ отправлен на кухню сотрудником {actor.full_name}",
    )

    return order


@transaction.atomic
def start_preparing(*, order, actor):
    """
    Начать приготовление: new → preparing.

    order: Order
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "new":
        raise OrderBusinessError("invalid_status", "Начать приготовление можно только из статуса new.")

    order.status = "preparing"
    order.save(update_fields=["status", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="preparing",
        old_status="new",
        new_status="preparing",
        details=f"Приготовление начато поваром {actor.full_name}",
    )

    return order


@transaction.atomic
def mark_ready(*, order, actor):
    """
    Отметить готовность: preparing → ready.

    order: Order
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "preparing":
        raise OrderBusinessError("invalid_status", "Отметить готовым можно только из статуса preparing.")

    order.status = "ready"
    order.save(update_fields=["status", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="ready",
        old_status="preparing",
        new_status="ready",
        details=f"Заказ готов. Отметил {actor.full_name}",
    )

    return order


@transaction.atomic
def mark_served(*, order, actor):
    """
    Отметить подачу: ready → served.

    order: Order
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "ready":
        raise OrderBusinessError("invalid_status", "Отметить поданным можно только из статуса ready.")

    order.status = "served"
    order.save(update_fields=["status", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="served",
        old_status="ready",
        new_status="served",
        details=f"Заказ подан гостю. Отметил {actor.full_name}",
    )

    return order


@transaction.atomic
def mark_paid(*, order, payment_method, actor):
    """
    Отметить оплату (только served, is_paid=False).

    order: Order
    payment_method: str (cash/card)
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "served":
        raise OrderBusinessError("invalid_status", "Оплатить можно только заказ в статусе served.")

    if order.is_paid:
        raise OrderBusinessError("already_paid", "Заказ уже оплачен.")

    if payment_method not in ("cash", "card"):
        raise OrderBusinessError("invalid_payment_method", "Метод оплаты должен быть cash или card.")

    # Проверка, что сумма > 0
    total = order.total
    if total <= Decimal("0.00"):
        raise OrderBusinessError("empty_order", "Сумма заказа должна быть больше 0.")

    order.is_paid = True
    order.payment_method = payment_method
    order.paid_at = timezone.now()
    order.paid_by = actor
    order.save(update_fields=["is_paid", "payment_method", "paid_at", "paid_by", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="paid",
        old_status="served",
        new_status="served",
        details=f"Оплата получена ({payment_method}). Принял {actor.full_name}",
    )

    return order


@transaction.atomic
def close_order(*, order, actor):
    """
    Закрыть заказ: served + is_paid=True → closed.

    order: Order
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status != "served":
        raise OrderBusinessError("invalid_status", "Закрыть можно только заказ в статусе served.")

    if not order.is_paid:
        raise OrderBusinessError("payment_required", "Нельзя закрыть заказ без оплаты.")

    order.status = "closed"
    order.closed_at = timezone.now()
    order.save(update_fields=["status", "closed_at", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="closed",
        old_status="served",
        new_status="closed",
        details=f"Заказ закрыт сотрудником {actor.full_name}",
    )

    return order


@transaction.atomic
def cancel_order(*, order, reason, actor):
    """
    Отменить заказ: draft/new → cancelled.

    order: Order
    reason: str
    actor: EmployeeProfile
    """
    _validate_actor(actor)
    order = _lock_order(order.pk)

    if order.status not in ("draft", "new"):
        raise OrderBusinessError("invalid_status", "Отменить можно только заказ в статусе draft или new.")

    if order.is_paid:
        raise OrderBusinessError("already_paid", "Нельзя отменить оплаченный заказ.")

    if not reason or not reason.strip():
        raise OrderBusinessError("missing_reason", "Причина отмены обязательна.")

    old_status = order.status
    order.status = "cancelled"
    order.save(update_fields=["status", "updated_at"])

    OrderHistory.objects.create(
        order=order,
        actor=actor,
        action="cancelled",
        old_status=old_status,
        new_status="cancelled",
        details=f"Заказ отменён сотрудником {actor.full_name}. Причина: {reason.strip()}",
    )

    return order
