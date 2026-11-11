import uuid
from django.db import models
from django.db.models import Q



class Cart(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

    def __str__(self):
        return str(self.id)

    class Meta:
        verbose_name = 'Корзина'
        verbose_name_plural = 'Корзины'


class CartItem(models.Model):
    cart = models.ForeignKey('cart.Cart', on_delete=models.CASCADE, related_name='items')
    dish = models.ForeignKey('catalog.Dish', on_delete=models.PROTECT, related_name='cart_items')
    quantity = models.PositiveIntegerField(default=1)

    def __str__(self):
        return f'{self.dish.name} x {self.quantity}'

    class Meta:
        verbose_name = 'Позиция корзины'
        verbose_name_plural = 'Позиции корзины'
        constraints = [
            models.UniqueConstraint(
                fields=['cart', 'dish'],
                name='cart_unique_dish_per_cart',
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1) & Q(quantity__lte=99),
                name='cart_item_quantity_1_99',
            ),
        ]