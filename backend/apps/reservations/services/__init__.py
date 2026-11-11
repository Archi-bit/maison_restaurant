"""Публичный интерфейс доменных сервисов. Бекзат импортирует только отсюда."""
from .availability import ReservationBusinessError, get_hall_plan
from .reservation_service import (
    cancel_reservation,
    confirm_reservation,
    create_public_reservation,
    create_staff_reservation,
    mark_arrived,
    update_reservation,
)
from .table_service import assign_table

__all__ = [
    "ReservationBusinessError",
    "create_public_reservation",
    "create_staff_reservation",
    "update_reservation",
    "confirm_reservation",
    "mark_arrived",
    "cancel_reservation",
    "assign_table",
    "get_hall_plan",
]
