import hashlib
import secrets
from datetime import timedelta
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, NotFound, ValidationError
from apps.catalog.models import Dish
from .models import Cart, CartItem



class CartTokenError(APIException):
    status_code = 401
    default_detail = 'Недействительный или просроченный токен корзины.'
    default_code = 'invalid_cart_token'


def create_cart():
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    cart = Cart.objects.create(
        token_hash=token_hash,
        expires_at=timezone.now() + timedelta(days=30),
    )

    return cart, token


def get_cart_by_token(token):
    if not isinstance(token, str) or not token or len(token) > 200:
        raise CartTokenError()

    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()

    cart = Cart.objects.filter(token_hash=token_hash).first()

    if cart is None or cart.expires_at <= timezone.now():
        raise CartTokenError()

    return cart


def validate_quantity(quantity):
    if type(quantity) is not int or not 1 <= quantity <= 99:
        raise ValidationError({
            'quantity': 'Количество должно быть целым числом от 1 до 99.'
        })


def get_available_dish(dish_id):
    dish = Dish.objects.select_related('category').filter(pk=dish_id).first()

    if dish is None:
        raise NotFound('Блюдо не найдено.')

    if not dish.is_active or not dish.is_available or not dish.category.is_active:
        raise ValidationError({
            'dish_id': 'Это блюдо сейчас недоступно для добавления.'
        })

    return dish


def add_cart_item(cart, dish_id, quantity):
    validate_quantity(quantity)

    with transaction.atomic():
        Cart.objects.select_for_update().get(pk=cart.pk)

        dish = get_available_dish(dish_id)

        item = CartItem.objects.filter(
            cart_id=cart.pk,
            dish_id=dish.pk,
        ).first()

        if item is None:
            CartItem.objects.create(
                cart_id=cart.pk,
                dish=dish,
                quantity=quantity,
            )
            created = True
        else:
            new_quantity = item.quantity + quantity
            validate_quantity(new_quantity)

            item.quantity = new_quantity
            item.save(update_fields=['quantity'])
            created = False

        Cart.objects.filter(pk=cart.pk).update(updated_at=timezone.now())

    return created


def update_cart_item(cart, item_id, quantity):
    validate_quantity(quantity)

    with transaction.atomic():
        Cart.objects.select_for_update().get(pk=cart.pk)

        item = CartItem.objects.select_related(
            'dish__category'
        ).filter(
            cart_id=cart.pk,
            id=item_id,
        ).first()

        if item is None:
            raise NotFound('Позиция корзины не найдена.')

        if quantity > item.quantity:
            dish = item.dish

            if not dish.is_active or not dish.is_available or not dish.category.is_active:
                raise ValidationError({
                    'quantity': 'Нельзя увеличить количество недоступного блюда.'
                })

        item.quantity = quantity
        item.save(update_fields=['quantity'])

        Cart.objects.filter(pk=cart.pk).update(updated_at=timezone.now())

    return item


def delete_cart_item(cart, item_id):
    with transaction.atomic():
        Cart.objects.select_for_update().get(pk=cart.pk)

        item = CartItem.objects.filter(
            cart_id=cart.pk,
            id=item_id,
        ).first()

        if item is None:
            raise NotFound('Позиция корзины не найдена.')

        item.delete()

        Cart.objects.filter(pk=cart.pk).update(updated_at=timezone.now())


def calculate_cart_totals(cart):
    items = cart.items.select_related('dish').all()

    items_count = 0
    subtotal = Decimal('0.00')

    for item in items:
        items_count += item.quantity
        subtotal += item.dish.price * item.quantity

    return {
        'items_count': items_count,
        'subtotal': subtotal,
        'total': subtotal,
    }