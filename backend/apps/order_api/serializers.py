from rest_framework import serializers

from apps.orders.models import Order, OrderHistory, OrderItem
from apps.reservation_api.serializers import StrictSerializer
from apps.staff.models import EmployeeProfile


KITCHEN_STATUSES = ("new", "preparing", "ready")


class OrderCreateSerializer(StrictSerializer):
    channel = serializers.ChoiceField(choices=Order.CHANNEL_CHOICES)
    reservation_id = serializers.IntegerField(min_value=1, required=False)
    note = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        has_reservation = "reservation_id" in attrs
        if attrs["channel"] == "dine_in" and not has_reservation:
            raise serializers.ValidationError({
                "reservation_id": "Для dine_in требуется бронь."
            })
        if attrs["channel"] != "dine_in" and has_reservation:
            raise serializers.ValidationError({
                "reservation_id": "Бронь указывается только для dine_in."
            })
        return attrs


class OrderItemUpdateSerializer(StrictSerializer):
    quantity = serializers.IntegerField(min_value=1, max_value=99, required=False)
    note = serializers.CharField(max_length=255, required=False, allow_blank=True)


class OrderItemCreateSerializer(OrderItemUpdateSerializer):
    dish_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class OrderPaySerializer(StrictSerializer):
    method = serializers.ChoiceField(
        source="payment_method", choices=Order.PAYMENT_METHOD_CHOICES
    )


class OrderCancelSerializer(StrictSerializer):
    reason = serializers.CharField()

    def validate_reason(self, value):
        if not isinstance(self.initial_data["reason"], str):
            raise serializers.ValidationError("Причина должна быть строкой.")
        return value


class OrderStatusFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Order.STATUS_CHOICES, required=False)


class OrderFilterSerializer(OrderStatusFilterSerializer):
    channel = serializers.ChoiceField(choices=Order.CHANNEL_CHOICES, required=False)
    date = serializers.DateField(required=False)
    table_id = serializers.IntegerField(min_value=1, required=False)


class KitchenFilterSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=KITCHEN_STATUSES, required=False)
    station = serializers.ChoiceField(choices=OrderItem.STATION_CHOICES, required=False)


class OrderItemReadSerializer(serializers.ModelSerializer):
    dish_id = serializers.IntegerField(read_only=True)
    unit_price = serializers.DecimalField(
        max_digits=10, decimal_places=2, coerce_to_string=True, read_only=True
    )
    line_total = serializers.DecimalField(
        max_digits=12, decimal_places=2, coerce_to_string=True, read_only=True
    )

    class Meta:
        model = OrderItem
        fields = (
            "id", "dish_id", "dish_name", "quantity", "unit_price",
            "line_total", "station", "note",
        )
        read_only_fields = fields


class OrderHistorySerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor.full_name", read_only=True, allow_null=True)

    class Meta:
        model = OrderHistory
        fields = ("action", "actor", "old_status", "new_status", "details", "created_at")
        read_only_fields = fields


class OrderWaiterSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeProfile
        fields = ("id", "full_name")
        read_only_fields = fields


class OrderListSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    table_id = serializers.IntegerField(read_only=True, allow_null=True)
    table_code = serializers.CharField(source="table.code", read_only=True, allow_null=True)
    waiter = OrderWaiterSerializer(read_only=True, allow_null=True)
    total = serializers.DecimalField(
        max_digits=None, decimal_places=2, coerce_to_string=True, read_only=True
    )

    class Meta:
        model = Order
        fields = (
            "id", "number", "channel", "table_id", "table_code", "waiter",
            "status", "is_paid", "total", "created_at",
        )
        read_only_fields = fields


class OrderDetailSerializer(OrderListSerializer):
    url = serializers.HyperlinkedIdentityField(view_name="order_api:order-detail")
    reservation_id = serializers.IntegerField(read_only=True, allow_null=True)
    shift_id = serializers.IntegerField(read_only=True)
    created_by_id = serializers.IntegerField(read_only=True, allow_null=True)
    paid_by_id = serializers.IntegerField(read_only=True, allow_null=True)
    items = OrderItemReadSerializer(many=True, read_only=True)
    history = OrderHistorySerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(
        source="total", max_digits=None, decimal_places=2,
        coerce_to_string=True, read_only=True,
    )
    currency = serializers.ChoiceField(choices=("KGS",), default="KGS", read_only=True)

    class Meta(OrderListSerializer.Meta):
        fields = OrderListSerializer.Meta.fields + (
            "url", "reservation_id", "shift_id", "created_by_id", "note", "items",
            "history", "subtotal", "currency", "payment_method", "paid_at",
            "paid_by_id", "closed_at", "updated_at",
        )
        read_only_fields = fields


class KitchenOrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ("dish_name", "quantity", "station", "note")
        read_only_fields = fields


class KitchenOrderSerializer(serializers.ModelSerializer):
    number = serializers.CharField(read_only=True)
    table_code = serializers.CharField(source="table.code", read_only=True, allow_null=True)
    status = serializers.ChoiceField(choices=KITCHEN_STATUSES, read_only=True)
    items = KitchenOrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = ("id", "number", "table_code", "channel", "created_at", "status", "items")
        read_only_fields = fields
