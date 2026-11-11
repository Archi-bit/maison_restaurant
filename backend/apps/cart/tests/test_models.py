from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Category, Dish
from apps.cart.models import Cart, CartItem


class CartModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Горячее', slug='hot')
        cls.dish = Dish.objects.create(
            category=cls.category, name='Паста', slug='pasta',
            price=Decimal('300.00'), image='dishes/pasta.jpg',
        )
        cls.cart = Cart.objects.create(
            token_hash='a' * 64,
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_cart_id_is_uuid_and_string(self):
        self.assertEqual(str(self.cart), str(self.cart.pk))
        self.assertEqual(len(str(self.cart.pk)), 36)

    def test_unique_cart_and_dish_constraint(self):
        CartItem.objects.create(cart=self.cart, dish=self.dish, quantity=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CartItem.objects.create(cart=self.cart, dish=self.dish, quantity=2)

    def test_quantity_database_constraint(self):
        for quantity in (0, 100):
            with self.subTest(quantity=quantity):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        CartItem.objects.create(
                            cart=self.cart, dish=self.dish, quantity=quantity,
                        )

    def test_cart_delete_cascades_items(self):
        CartItem.objects.create(cart=self.cart, dish=self.dish, quantity=2)
        self.cart.delete()
        self.assertEqual(CartItem.objects.count(), 0)
