from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import CartItemCreateSerializer, CartItemUpdateSerializer, CartSerializer
from .services import (
    add_cart_item,
    create_cart,
    delete_cart_item,
    get_cart_by_token,
    update_cart_item,
)


CART_TOKEN_PARAMETER = OpenApiParameter(
    name='X-Cart-Token',
    type=str,
    location=OpenApiParameter.HEADER,
    required=True,
    description='Секретный токен гостевой корзины',
)

TOKEN_ERROR = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description='Отсутствующий, неверный или просроченный токен.',
    examples=[
        OpenApiExample(
            'Недействительный токен',
            value={'detail': 'Недействительный или просроченный токен корзины.'},
            response_only=True,
            status_codes=['401'],
        ),
    ],
)

VALIDATION_ERROR = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description='Неверное количество либо недоступное блюдо.',
    examples=[
        OpenApiExample(
            'Неверное количество',
            value={'quantity': ['Ensure this value is greater than or equal to 1.']},
            response_only=True,
            status_codes=['400'],
        ),
    ],
)

ITEM_NOT_FOUND = OpenApiResponse(
    response=OpenApiTypes.OBJECT,
    description='Блюдо или позиция корзины не найдены (в том числе в другой корзине).',
    examples=[
        OpenApiExample(
            'Позиция не найдена',
            value={'detail': 'Позиция корзины не найдена.'},
            response_only=True,
            status_codes=['404'],
        ),
    ],
)


class CartTokenMixin:
    def get_cart(self, request):
        return get_cart_by_token(request.headers.get('X-Cart-Token'))

    def serialize_cart(self, cart, request):
        return CartSerializer(cart, context={'request': request}).data


class CartDetailView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary='Получить гостевую корзину',
        parameters=[CART_TOKEN_PARAMETER],
        responses={200: CartSerializer, 401: TOKEN_ERROR},
    )
    def get(self, request):
        cart = self.get_cart(request)
        return Response(self.serialize_cart(cart, request), status=status.HTTP_200_OK)


class CartCreateView(CartDetailView):
    @extend_schema(
        summary='Создать гостевую корзину',
        request=None,
        responses={
            201: inline_serializer(
                name='CartCreateResponse',
                fields={
                    'cart_token': serializers.CharField(),
                    'cart': CartSerializer(),
                },
            ),
        },
    )
    def post(self, request):
        cart, token = create_cart()
        return Response(
            {'cart_token': token, 'cart': self.serialize_cart(cart, request)},
            status=status.HTTP_201_CREATED,
        )


class CartItemCreateView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary='Добавить блюдо в корзину',
        parameters=[CART_TOKEN_PARAMETER],
        request=CartItemCreateSerializer,
        responses={
            200: CartSerializer,
            201: CartSerializer,
            400: VALIDATION_ERROR,
            401: TOKEN_ERROR,
            404: ITEM_NOT_FOUND,
        },
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
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(self.serialize_cart(cart, request), status=response_status)


class CartItemDetailView(CartTokenMixin, APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        summary='Изменить количество блюда',
        parameters=[CART_TOKEN_PARAMETER],
        request=CartItemUpdateSerializer,
        responses={
            200: CartSerializer,
            400: VALIDATION_ERROR,
            401: TOKEN_ERROR,
            404: ITEM_NOT_FOUND,
        },
    )
    def patch(self, request, id):
        cart = self.get_cart(request)
        serializer = CartItemUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_cart_item(
            cart=cart, item_id=id, quantity=serializer.validated_data['quantity'],
        )
        return Response(self.serialize_cart(cart, request), status=status.HTTP_200_OK)

    @extend_schema(
        summary='Удалить позицию корзины',
        parameters=[CART_TOKEN_PARAMETER],
        request=None,
        responses={
            204: OpenApiResponse(description='Позиция удалена; тело ответа отсутствует.'),
            401: TOKEN_ERROR,
            404: ITEM_NOT_FOUND,
        },
    )
    def delete(self, request, id):
        cart = self.get_cart(request)
        delete_cart_item(cart=cart, item_id=id)
        return Response(status=status.HTTP_204_NO_CONTENT)
