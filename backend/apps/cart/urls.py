from django.urls import path
from .views import (CartCreateView, CartItemCreateView, CartItemDetailView)



urlpatterns = [
    path('cart/', CartCreateView.as_view(), name='cart-create'),
    path('cart/items/', CartItemCreateView.as_view(), name='cart-item-create'),
    path('cart/items/<int:id>/', CartItemDetailView.as_view(), name='cart-item-detail'),
]