from datetime import timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.catalog.models import Category, Dish
from apps.cart.models import Cart, CartItem


class CartApiTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name='Десерты', slug='desserts')
        cls.dish = Dish.objects.create(
            category=cls.category, name='Фондан', slug='fondant',
            price=Decimal('590.00'), image='dishes/fondant.jpg',
        )

    def setUp(self):
        response = self.client.post(reverse('cart-create'))
        self.assertEqual(response.status_code, 201)
        self.token = response.data['cart_token']
        self.cart_id = response.data['cart']['id']
        self.client.credentials(HTTP_X_CART_TOKEN=self.token)

    def add(self, quantity=1, dish_id=None):
        return self.client.post(
            reverse('cart-item-create'),
            {'dish_id': dish_id or self.dish.pk, 'quantity': quantity},
            format='json',
        )

    def test_empty_cart_and_persistence(self):
        response = self.client.get(reverse('cart-create'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.cart_id)
        self.assertEqual(response.data['items'], [])
        self.assertEqual(response.data['total'], '0.00')
        self.assertEqual(response.data['currency'], 'KGS')

    def test_add_and_repeat_add(self):
        first = self.add(quantity=2)
        second = self.add(quantity=1)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(len(second.data['items']), 1)
        self.assertEqual(second.data['items'][0]['quantity'], 3)
        self.assertEqual(second.data['items_count'], 3)
        self.assertEqual(second.data['total'], '1770.00')
        self.assertEqual(second.data['items'][0]['line_total'], '1770.00')

    def test_update_quantity(self):
        item_id = self.add().data['items'][0]['id']
        response = self.client.patch(
            reverse('cart-item-detail', args=[item_id]),
            {'quantity': 4}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['items_count'], 4)
        self.assertEqual(response.data['total'], '2360.00')

    def test_delete(self):
        item_id = self.add().data['items'][0]['id']
        response = self.client.delete(reverse('cart-item-detail', args=[item_id]))
        self.assertEqual(response.status_code, 204)
        self.assertIsNone(response.data)
        self.assertEqual(self.client.get(reverse('cart-create')).data['items'], [])

    def test_invalid_quantities_return_400(self):
        for quantity in (0, -1, 100, 1.5):
            with self.subTest(quantity=quantity):
                self.assertEqual(self.add(quantity=quantity).status_code, 400)

    def test_missing_dish_returns_404(self):
        self.assertEqual(self.add(dish_id=999999).status_code, 404)

    def test_unavailable_dish_returns_400(self):
        self.dish.is_available = False
        self.dish.save(update_fields=['is_available'])
        self.assertEqual(self.add().status_code, 400)

    def test_no_token_and_invalid_token_return_401(self):
        self.client.credentials()
        self.assertEqual(self.client.get(reverse('cart-create')).status_code, 401)
        self.assertEqual(self.add().status_code, 401)
        self.client.credentials(HTTP_X_CART_TOKEN='wrong')
        self.assertEqual(self.client.get(reverse('cart-create')).status_code, 401)

    def test_expired_token_returns_401(self):
        Cart.objects.filter(pk=self.cart_id).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.client.get(reverse('cart-create')).status_code, 401)

    def test_cannot_modify_another_carts_item(self):
        other_response = self.client.post(reverse('cart-create'))
        other_token = other_response.data['cart_token']
        other_cart_id = other_response.data['cart']['id']
        foreign = CartItem.objects.create(
            cart_id=other_cart_id, dish=self.dish, quantity=2,
        )
        item_url = reverse('cart-item-detail', args=[foreign.pk])
        self.assertEqual(
            self.client.patch(item_url, {'quantity': 3}, format='json').status_code,
            404,
        )
        self.assertEqual(self.client.delete(item_url).status_code, 404)
        self.client.credentials(HTTP_X_CART_TOKEN=other_token)
        self.assertEqual(self.client.get(reverse('cart-create')).status_code, 200)
        self.assertEqual(CartItem.objects.get(pk=foreign.pk).quantity, 2)

    def test_invalid_patch_returns_400(self):
        item_id = self.add().data['items'][0]['id']
        response = self.client.patch(
            reverse('cart-item-detail', args=[item_id]),
            {'quantity': 0}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_deleted_item_returns_404(self):
        self.assertEqual(
            self.client.delete(reverse('cart-item-detail', args=[999999])).status_code,
            404,
        )

    def test_price_cannot_be_submitted_by_client(self):
        response = self.client.post(
            reverse('cart-item-create'),
            {'dish_id': self.dish.pk, 'quantity': 1, 'unit_price': '0.01'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['total'], '590.00')
