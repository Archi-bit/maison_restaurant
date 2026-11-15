from django.urls import path

from apps.orders import services

from .views import (
    KitchenOrderActionView,
    KitchenOrderListView,
    OrderActionView,
    OrderCancelView,
    OrderDetailView,
    OrderItemCreateView,
    OrderItemDetailView,
    OrderListCreateView,
    OrderPayView,
    OrderReadyView,
    WaiterOrderListView,
)


app_name = "order_api"

urlpatterns = [
    path("staff/orders/", OrderListCreateView.as_view(), name="order-list"),
    path("staff/orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path(
        "staff/orders/<int:pk>/items/", OrderItemCreateView.as_view(), name="order-items"
    ),
    path(
        "staff/orders/<int:pk>/items/<int:item_id>/",
        OrderItemDetailView.as_view(),
        name="order-item-detail",
    ),
    path(
        "staff/orders/<int:pk>/send/",
        OrderActionView.as_view(service=services.send_to_kitchen),
        name="order-send",
    ),
    path(
        "staff/orders/<int:pk>/preparing/",
        KitchenOrderActionView.as_view(service=services.start_preparing),
        name="order-preparing",
    ),
    path("staff/orders/<int:pk>/ready/", OrderReadyView.as_view(), name="order-ready"),
    path(
        "staff/orders/<int:pk>/serve/",
        OrderActionView.as_view(service=services.mark_served),
        name="order-serve",
    ),
    path("staff/orders/<int:pk>/pay/", OrderPayView.as_view(), name="order-pay"),
    path(
        "staff/orders/<int:pk>/close/",
        OrderActionView.as_view(service=services.close_order),
        name="order-close",
    ),
    path("staff/orders/<int:pk>/cancel/", OrderCancelView.as_view(), name="order-cancel"),
    path("staff/kitchen/orders/", KitchenOrderListView.as_view(), name="kitchen-orders"),
    path("staff/waiter/orders/", WaiterOrderListView.as_view(), name="waiter-orders"),
]
