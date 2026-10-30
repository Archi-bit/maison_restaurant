from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Category, Dish


class CatalogApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Напитки", slug="drinks")
        cls.other_category = Category.objects.create(
            name="Десерты", slug="desserts", sort_order=1
        )
        cls.dish = Dish.objects.create(
            category=cls.category,
            name="Чай",
            slug="tea",
            price=Decimal("120.00"),
            image="dishes/tea.jpg",
            is_featured=True,
        )
        Dish.objects.create(
            category=cls.other_category,
            name="Торт",
            slug="cake",
            price=Decimal("250.00"),
            image="dishes/cake.jpg",
        )

    def test_category_list_returns_only_active_categories(self):
        Category.objects.create(name="Архив", slug="archived", is_active=False)

        response = self.client.get(reverse("category-list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [category["slug"] for category in response.data],
            ["drinks", "desserts"],
        )

    def test_dish_list_filters_by_category_and_featured(self):
        response = self.client.get(
            reverse("dish-list"),
            {"category": "drinks", "featured": "true"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["slug"], "tea")
        self.assertEqual(response.data["results"][0]["price"], "120.00")

    def test_dish_list_rejects_invalid_featured_value(self):
        response = self.client.get(reverse("dish-list"), {"featured": "yes"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("featured", response.data)

    def test_dish_detail_returns_dish_by_slug(self):
        response = self.client.get(reverse("dish-detail", args=["tea"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Чай")
        self.assertEqual(response.data["description"], "")

    def test_inactive_category_hides_its_dishes(self):
        self.category.is_active = False
        self.category.save(update_fields=["is_active"])

        response = self.client.get(reverse("dish-detail", args=["tea"]))

        self.assertEqual(response.status_code, 404)
