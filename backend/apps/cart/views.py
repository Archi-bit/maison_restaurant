from drf_spectacular.utils import (OpenApiParameter, OpenApiResponse, extend_schema, inline_serializer)
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .serializers import (CartSerializer, CartItemCreateSerializer, CartItemUpdateSerializer)
from .services import (create_cart, get_cart_by_token, add_cart_item, update_cart_item, delete_cart_item)



CART_TOKEN_PARAMETER = OpenApiParameter(
    name='X-Cart-Token',
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Секретный токен гостевой корзины',
)


class CartTokenMixin:
    def get_cart(self, request):
        token = request.headers.get('X-Cart-Token')
        return get_cart_by_token(token)

    def serialize_cart(self, cart, request):
        return CartSerializer(cart,context={'request': request}).data


class CartDetailView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[CART_TOKEN_PARAMETER],
        responses={200: CartSerializer},
    )
    def get(self, request):
        cart = self.get_cart(request)

        return Response(self.serialize_cart(cart, request), status=status.HTTP_200_OK)


class CartCreateView(CartDetailView):
    @extend_schema(
        request=None,
        responses={
            201: inline_serializer(
                name='CartCreateResponse',
                fields={'cart_token': serializers.CharField(), 'cart': CartSerializer()},
            )
        },
    )
    def post(self, request):
        cart, token = create_cart()

        return Response(
            {
                'cart_token': token,
                'cart': self.serialize_cart(cart, request),
            },
            status=status.HTTP_201_CREATED,
        )


class CartItemCreateView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[CART_TOKEN_PARAMETER],
        request=CartItemCreateSerializer,
        responses={200: CartSerializer, 201: CartSerializer},
    )
    def post(self, request):
        cart = self.get_cart(request)

        serializer = CartItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        created = add_cart_item(
            cart=cart,
            dish_id=serializer.validated_data['dish_id'],
            quantity=serializer.validated_data['quantity'],
        )

        response_status = (status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        return Response(
            self.serialize_cart(cart, request),
            status=response_status,
        )


class CartItemDetailView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[CART_TOKEN_PARAMETER],
        request=CartItemUpdateSerializer,
        responses={200: CartSerializer},
    )
    def patch(self, request, id):
        cart = self.get_cart(request)

        serializer = CartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        update_cart_item(
            cart=cart,
            item_id=id,
            quantity=serializer.validated_data['quantity'],
        )

        return Response(self.serialize_cart(cart, request), status=status.HTTP_200_OK)

    @extend_schema(
        parameters=[CART_TOKEN_PARAMETER],
        responses={
            204: OpenApiResponse(description='Позиция удалена.')
        },
    )
    def delete(self, request, id):
        cart = self.get_cart(request)

        delete_cart_item(cart=cart, item_id=id)

        return Response(status=status.HTTP_204_NO_CONTENT)