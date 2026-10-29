from rest_framework import serializers
from .models import Cart, CartItem
from .services import calculate_cart_totals



class CartItemSerializer(serializers.ModelSerializer):
    dish_id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source='dish.name', read_only=True)
    image = serializers.ImageField(source='dish.image', read_only=True)
    unit_price = serializers.DecimalField(source='dish.price', max_digits=10, decimal_places=2, coerce_to_string=True, read_only=True)
    line_total = serializers.SerializerMethodField()

    class Meta:
        model = CartItem
        fields = ('id', 'dish_id', 'name', 'image', 'quantity', 'unit_price', 'line_total')
        read_only_fields = fields

    def get_line_total(self, obj):
        total = obj.dish.price * obj.quantity
        return f'{total:.2f}'


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    subtotal = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()

    class Meta:
        model = Cart
        fields = ('id', 'items', 'items_count', 'subtotal', 'total', 'currency')
        read_only_fields = fields

    def _get_totals(self, obj):
        if not hasattr(self, '_totals_cache'):
            self._totals_cache = {}

        if obj.pk not in self._totals_cache:
            self._totals_cache[obj.pk] = calculate_cart_totals(obj)

        return self._totals_cache[obj.pk]

    def get_items_count(self, obj):
        return self._get_totals(obj)['items_count']

    def get_subtotal(self, obj):
        return f"{self._get_totals(obj)['subtotal']:.2f}"

    def get_total(self, obj):
        return f"{self._get_totals(obj)['total']:.2f}"

    def get_currency(self, obj):
        return 'KGS'


class CartItemCreateSerializer(serializers.Serializer):
    dish_id = serializers.IntegerField(min_value=1)
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class CartItemUpdateSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(min_value=1, max_value=99)