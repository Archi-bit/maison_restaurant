from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from django.db import close_old_connections
from django.test import TransactionTestCase

from apps.catalog.models import Category, Dish
from apps.cart.models import Cart, CartItem
from apps.cart.services import add_cart_item, create_cart


class CartConcurrencyTests(TransactionTestCase):
    def test_two_concurrent_adds_do_not_duplicate_item(self):
        category = Category.objects.create(name='Горячее', slug='hot')
        dish = Dish.objects.create(
            category=category, name='Паста', slug='pasta',
            price=Decimal('400.00'), image='dishes/pasta.jpg',
        )
        cart, _ = create_cart()

        def add_one():
            close_old_connections()
            try:
                return add_cart_item(cart, dish.pk, 1)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: add_one(), range(2)))

        self.assertCountEqual(results, [True, False])
        self.assertEqual(Cart.objects.count(), 1)
        items = CartItem.objects.filter(cart=cart)
        self.assertEqual(items.count(), 1)
        self.assertEqual(items.get().quantity, 2)
