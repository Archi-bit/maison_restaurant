"""Общие помощники для тестов."""
from datetime import time, timedelta

from apps.reservations.services.availability import now_local


def future_date(days=3):
    return (now_local() + timedelta(days=days)).date()


def public_data(**overrides):
    data = {
        "guest_name": "Айбек",
        "phone": "+996700123456",
        "date": future_date(),
        "start_time": time(14, 0),
        "guests_count": 2,
        "guest_note": "",
    }
    data.update(overrides)
    return data


# Если в проекте можно создать staff.EmployeeProfile в тестах — подставь сюда
# реального сотрудника, чтобы проверять created_by / responsible_employee по-настоящему.
ACTOR = None
