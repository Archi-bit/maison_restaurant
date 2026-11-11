from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.catalog.models import Category, Dish
from apps.cart.models import Cart, CartItem
from apps.cart.services import (
    CartTokenError,
    add_cart_item,
    calculate_cart_totals,
    create_cart,
    delete_cart_item,
    get_cart_by_token,
    update_cart_item,
)


class CartServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Закуски', slug='appetizers')
        cls.dish = Dish.objects.create(
            category=cls.category, name='Тартар', slug='tartare',
            price=Decimal('990.00'), image='dishes/tartare.jpg',
        )

    def setUp(self):
        self.cart, self.token = create_cart()

    def test_token_is_hashed_and_valid_for_30_days(self):
        self.assertNotEqual(self.token, self.cart.token_hash)
        self.assertEqual(len(self.cart.token_hash), 64)
        self.assertEqual(get_cart_by_token(self.token), self.cart)
        self.assertGreater(self.cart.expires_at, timezone.now() + timedelta(days=29))

    def test_wrong_missing_expired_token_rejected(self):
        for token in (None, '', 'invalid'):
            with self.subTest(token=token):
                with self.assertRaises(CartTokenError):
                    get_cart_by_token(token)
        self.cart.expires_at = timezone.now() - timedelta(seconds=1)
        self.cart.save(update_fields=['expires_at'])
        with self.assertRaises(CartTokenError):
            get_cart_by_token(self.token)

    def test_add_repeat_and_totals(self):
        self.assertTrue(add_cart_item(self.cart, self.dish.pk, 2))
        self.assertFalse(add_cart_item(self.cart, self.dish.pk, 1))
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 1)
        self.assertEqual(CartItem.objects.get(cart=self.cart).quantity, 3)
        totals = calculate_cart_totals(self.cart)
        self.assertEqual(totals['items_count'], 3)
        self.assertEqual(totals['total'], Decimal('2970.00'))

    def test_update_and_delete(self):
        add_cart_item(self.cart, self.dish.pk, 2)
        item = CartItem.objects.get(cart=self.cart)
        update_cart_item(self.cart, item.pk, 1)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)
        delete_cart_item(self.cart, item.pk)
        self.assertEqual(CartItem.objects.filter(cart=self.cart).count(), 0)

    def test_foreign_cart_item_is_not_accessible(self):
        other_cart, _ = create_cart()
        foreign = CartItem.objects.create(cart=other_cart, dish=self.dish)
        with self.assertRaises(NotFound):
            update_cart_item(self.cart, foreign.pk, 2)
        with self.assertRaises(NotFound):
            delete_cart_item(self.cart, foreign.pk)

    def test_unavailable_dish_cannot_be_added(self):
        self.dish.is_available = False
        self.dish.save(update_fields=['is_available'])
        with self.assertRaises(ValidationError):
            add_cart_item(self.cart, self.dish.pk, 1)

    def test_existing_unavailable_dish_can_decrease_but_not_increase(self):
        add_cart_item(self.cart, self.dish.pk, 3)
        item = CartItem.objects.get(cart=self.cart)
        self.dish.is_available = False
        self.dish.save(update_fields=['is_available'])
        with self.assertRaises(ValidationError):
            update_cart_item(self.cart, item.pk, 4)
        update_cart_item(self.cart, item.pk, 2)
        self.assertEqual(CartItem.objects.get(pk=item.pk).quantity, 2)
        self.assertEqual(calculate_cart_totals(self.cart)['total'], Decimal('1980.00'))

    def test_inactive_category_cannot_be_added(self):
        self.category.is_active = False
        self.category.save(update_fields=['is_active'])
        with self.assertRaises(ValidationError):
            add_cart_item(self.cart, self.dish.pk, 1)

    def test_inactive_dish_cannot_be_added(self):
        self.dish.is_active = False
        self.dish.save(update_fields=['is_active'])
        with self.assertRaises(ValidationError):
            add_cart_item(self.cart, self.dish.pk, 1)

    def test_missing_dish_returns_not_found(self):
        with self.assertRaises(NotFound):
            add_cart_item(self.cart, 999999, 1)

    def test_total_uses_current_dish_price(self):
        add_cart_item(self.cart, self.dish.pk, 2)
        self.dish.price = Decimal('1000.00')
        self.dish.save(update_fields=['price'])
        self.assertEqual(calculate_cart_totals(self.cart)['total'], Decimal('2000.00'))

    def test_rejects_quantity_outside_range(self):
        for quantity in (0, -1, 100, 1.5, '2', True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValidationError):
                    add_cart_item(self.cart, self.dish.pk, quantity)

    def test_repeated_add_cannot_exceed_99(self):
        add_cart_item(self.cart, self.dish.pk, 99)
        with self.assertRaises(ValidationError):
            add_cart_item(self.cart, self.dish.pk, 1)
