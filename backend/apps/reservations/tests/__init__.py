"""Общие помощники для тестов."""
from datetime import time, timedelta

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase

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


def make_actor(username="waiter"):
    """Реальный staff.EmployeeProfile (без заглушек).

    ПРОВЕРИТЬ ПОСЛЕ ГОТОВНОСТИ МОДУЛЯ STAFF: если у EmployeeProfile есть обязательные поля
    (роль, телефон и т.п.) или профиль создаётся сигналом/другой фабрикой — поправить только
    эту функцию, остальные тесты от неё зависят.
    """
    user = get_user_model().objects.create_user(username=username, password="pass12345")
    profile_model = apps.get_model("staff", "EmployeeProfile")
    profile, _ = profile_model.objects.get_or_create(user=user)
    return profile


class ActorTestCase(TestCase):
    """База для тестов: self.actor — настоящий EmployeeProfile."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.actor = make_actor()
