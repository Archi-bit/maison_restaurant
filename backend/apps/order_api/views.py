from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, prefetch_related_objects
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiExample, OpenApiResponse, extend_schema, extend_schema_view,
)
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView, ListAPIView, get_object_or_404
from rest_framework.mixins import ListModelMixin
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.operations.models import RestaurantShift, ShiftTableAssignment
from apps.orders import services
from apps.orders.models import Order, OrderHistory, OrderItem
from apps.reservation_api.serializers import NoPayloadSerializer
from apps.reservations.models import Reservation
from apps.staff.models import EmployeeProfile
from apps.staff.permissions import HasEmployeeProfile, get_employee_profile

from .permissions import KITCHEN_ROLES, MANAGER_ROLES, ORDER_ROLES, HasOrderRole
from .serializers import (
    KITCHEN_STATUSES,
    KitchenFilterSerializer,
    KitchenOrderSerializer,
    OrderCancelSerializer,
    OrderCreateSerializer,
    OrderDetailSerializer,
    OrderFilterSerializer,
    OrderItemCreateSerializer,
    OrderItemUpdateSerializer,
    OrderListSerializer,
    OrderPaySerializer,
    OrderStatusFilterSerializer,
)


AUTH_ERRORS = {
    401: OpenApiResponse(OpenApiTypes.OBJECT, "Требуется действительный JWT."),
    403: OpenApiResponse(OpenApiTypes.OBJECT, "У сотрудника нет доступа к действию."),
}
NOT_FOUND = OpenApiResponse(OpenApiTypes.OBJECT, "Запись отсутствует или недоступна.")
BAD_REQUEST = OpenApiResponse(
    OpenApiTypes.OBJECT,
    "Ошибки входных полей или бизнес-ошибка с полями code и detail.",
)
DETAIL_ERRORS = {**AUTH_ERRORS, 404: NOT_FOUND}
ACTION_ERRORS = {**DETAIL_ERRORS, 400: BAD_REQUEST}
ORDER_ITEMS = Prefetch("items", queryset=OrderItem.objects.order_by("pk"))
ORDER_HISTORY = Prefetch(
    "history",
    queryset=OrderHistory.objects.select_related("actor").order_by("created_at", "pk"),
)


class OrderPagination(PageNumberPagination):
    page_size = 20


class StaffOrderView(GenericAPIView):
    permission_classes = (IsAuthenticated, HasEmployeeProfile, HasOrderRole)
    allowed_roles = ORDER_ROLES
    queryset = Order.objects.all()

    def get_queryset(self):
        queryset = super().get_queryset()
        employee = get_employee_profile(self.request.user)
        if employee is None:
            return queryset.none()
        if employee.role == EmployeeProfile.Role.WAITER:
            return queryset.filter(waiter=employee)
        return queryset

    def get_locked_order(self):
        # Сохраняем область доступа официанта до завершения операции.
        return get_object_or_404(
            self.get_queryset().select_for_update(), pk=self.kwargs["pk"]
        )

    def order_detail_response(self, order, response_status=status.HTTP_200_OK):
        prefetch_related_objects([order], ORDER_ITEMS, ORDER_HISTORY)
        return Response(
            OrderDetailSerializer(order, context=self.get_serializer_context()).data,
            status=response_status,
        )

    def handle_exception(self, exc):
        if isinstance(exc, services.OrderBusinessError):
            response_status = (
                status.HTTP_403_FORBIDDEN
                if exc.code == "access_denied"
                else status.HTTP_400_BAD_REQUEST
            )
            return Response({"code": exc.code, "detail": exc.message}, status=response_status)
        return super().handle_exception(exc)


class OrderListView(ListModelMixin, StaffOrderView):
    pagination_class = OrderPagination
    serializer_class = OrderListSerializer
    filter_serializer_class = OrderFilterSerializer

    def filter_queryset(self, queryset):
        query = self.filter_serializer_class(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = dict(query.validated_data)
        date = filters.pop("date", None)
        if date is not None:
            filters["created_at__date"] = date
        return (
            queryset.filter(**filters)
            .select_related("table", "waiter")
            .prefetch_related(ORDER_ITEMS)
            .order_by("-created_at", "-pk")
        )

    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)


@extend_schema_view(
    get=extend_schema(
        parameters=[OrderFilterSerializer],
        responses={200: OrderListSerializer(many=True), 400: BAD_REQUEST, **DETAIL_ERRORS},
    ),
)
class OrderListCreateView(OrderListView):
    @extend_schema(
        request=OrderCreateSerializer,
        responses={201: OrderDetailSerializer, 400: BAD_REQUEST, **AUTH_ERRORS},
        examples=[
            OpenApiExample(
                "Заказ в зале",
                value={"channel": "dine_in", "reservation_id": 27, "note": "Подать вместе"},
                request_only=True,
            ),
            OpenApiExample(
                "Заказ с собой",
                value={"channel": "takeaway", "note": "Упаковать отдельно"},
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request):
        serializer = OrderCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order_data = serializer.validated_data
        employee = request.user.employee_profile
        if employee.role == EmployeeProfile.Role.WAITER:
            self.check_waiter_table(employee, order_data)
        order = services.create_order(validated_data=order_data, actor=employee)
        return self.order_detail_response(order, status.HTTP_201_CREATED)

    def check_waiter_table(self, employee, order_data):
        if order_data["channel"] != "dine_in":
            raise PermissionDenied("Официант может создавать только заказы в зале.")
        # Сервис создания и переназначение столов блокируют ту же смену.
        shift = RestaurantShift.objects.select_for_update().filter(
            status=RestaurantShift.Status.OPEN
        ).first()
        if shift is None:
            raise PermissionDenied("Оформление заказа требует назначения стола в открытой смене.")
        assigned_tables = ShiftTableAssignment.objects.filter(
            shift=shift, waiter=employee
        ).values("table_id")
        if not Reservation.objects.select_for_update().filter(
            pk=order_data["reservation_id"], table_id__in=assigned_tables
        ).exists():
            raise PermissionDenied("Бронь для этого официанта недоступна.")


@extend_schema_view(
    get=extend_schema(
        parameters=[OrderStatusFilterSerializer],
        responses={200: OrderListSerializer(many=True), 400: BAD_REQUEST, **DETAIL_ERRORS},
    ),
)
class WaiterOrderListView(OrderListView):
    allowed_roles = (EmployeeProfile.Role.WAITER,)
    filter_serializer_class = OrderStatusFilterSerializer


class OrderDetailView(StaffOrderView):
    serializer_class = OrderDetailSerializer

    @extend_schema(responses={200: OrderDetailSerializer, **DETAIL_ERRORS})
    def get(self, request, pk):
        order = get_object_or_404(
            self.get_queryset().select_related("table", "waiter"), pk=pk
        )
        return self.order_detail_response(order)


class OrderItemCreateView(StaffOrderView):
    serializer_class = OrderItemCreateSerializer

    @extend_schema(
        request=OrderItemCreateSerializer,
        responses={201: OrderDetailSerializer, **ACTION_ERRORS},
        examples=[
            OpenApiExample(
                "Добавить две порции",
                value={"dish_id": 1, "quantity": 2, "note": "Без орехов"},
                request_only=True,
            ),
        ],
    )
    @transaction.atomic
    def post(self, request, pk):
        order = self.get_locked_order()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item_data = serializer.validated_data
        order = services.add_order_item(
            order=order,
            dish=item_data["dish_id"],
            quantity=item_data["quantity"],
            note=item_data.get("note", ""),
            actor=request.user.employee_profile,
        )
        return self.order_detail_response(order, status.HTTP_201_CREATED)


class OrderItemDetailView(StaffOrderView):
    serializer_class = OrderItemUpdateSerializer

    def get_item(self, item_id):
        order = self.get_locked_order()
        return get_object_or_404(order.items, pk=item_id)

    @extend_schema(
        request=OrderItemUpdateSerializer,
        responses={200: OrderDetailSerializer, **ACTION_ERRORS},
    )
    @transaction.atomic
    def patch(self, request, pk, item_id):
        item = self.get_item(item_id)
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        order = services.update_order_item(
            item=item, actor=request.user.employee_profile, **serializer.validated_data
        )
        return self.order_detail_response(order)

    @extend_schema(responses={204: None, **ACTION_ERRORS})
    @transaction.atomic
    def delete(self, request, pk, item_id):
        item = self.get_item(item_id)
        services.remove_order_item(item=item, actor=request.user.employee_profile)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderActionView(StaffOrderView):
    serializer_class = NoPayloadSerializer
    service = None

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: OrderDetailSerializer, **ACTION_ERRORS},
    )
    @transaction.atomic
    def post(self, request, pk):
        order = self.get_locked_order()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = self.service(
            order=order, actor=request.user.employee_profile, **serializer.validated_data
        )
        return self.action_response(order)

    def action_response(self, order):
        return self.order_detail_response(order)


class KitchenOrderActionView(OrderActionView):
    allowed_roles = KITCHEN_ROLES

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: KitchenOrderSerializer, **ACTION_ERRORS},
    )
    def post(self, request, pk):
        return super().post(request, pk)

    def action_response(self, order):
        prefetch_related_objects([order], ORDER_ITEMS)
        return Response(KitchenOrderSerializer(order).data)


class OrderReadyView(KitchenOrderActionView):
    service = staticmethod(services.mark_ready)

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: KitchenOrderSerializer, **ACTION_ERRORS},
        examples=[
            OpenApiExample(
                "Заказ готов",
                value={
                    "id": 42,
                    "number": "№0042",
                    "table_code": "T05",
                    "channel": "dine_in",
                    "created_at": "2026-11-12T19:18:00+06:00",
                    "status": "ready",
                    "items": [
                        {"dish_name": "Стейк", "quantity": 2, "station": "hot", "note": ""},
                    ],
                },
                response_only=True,
                status_codes=["200"],
            ),
            OpenApiExample(
                "Недопустимое состояние заказа",
                value={
                    "code": "invalid_status",
                    "detail": "Отметить готовым можно только из статуса preparing.",
                },
                response_only=True,
                status_codes=["400"],
            ),
        ],
    )
    def post(self, request, pk):
        return super().post(request, pk)


class OrderPayView(OrderActionView):
    serializer_class = OrderPaySerializer
    service = staticmethod(services.mark_paid)

    @extend_schema(
        request=OrderPaySerializer,
        responses={200: OrderDetailSerializer, **ACTION_ERRORS},
        examples=[
            OpenApiExample("Оплата наличными", value={"method": "cash"}, request_only=True),
            OpenApiExample(
                "Повторная оплата",
                value={"code": "already_paid", "detail": "Заказ уже оплачен."},
                response_only=True,
                status_codes=["400"],
            ),
        ],
    )
    def post(self, request, pk):
        return super().post(request, pk)


class OrderCancelView(OrderActionView):
    allowed_roles = MANAGER_ROLES
    serializer_class = OrderCancelSerializer
    service = staticmethod(services.cancel_order)

    @extend_schema(
        request=OrderCancelSerializer,
        responses={200: OrderDetailSerializer, **ACTION_ERRORS},
    )
    def post(self, request, pk):
        return super().post(request, pk)


class KitchenOrderListView(ListAPIView, StaffOrderView):
    allowed_roles = KITCHEN_ROLES
    serializer_class = KitchenOrderSerializer
    pagination_class = OrderPagination

    def filter_queryset(self, queryset):
        query = KitchenFilterSerializer(data=self.request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        items = OrderItem.objects.order_by("pk")
        queryset = queryset.filter(
            status__in=(filters["status"],) if "status" in filters else KITCHEN_STATUSES
        )
        if "station" in filters:
            items = items.filter(station=filters["station"])
            queryset = queryset.filter(Exists(items.filter(order_id=OuterRef("pk"))))
        return (
            queryset.select_related("table")
            .prefetch_related(Prefetch("items", queryset=items))
            .order_by("created_at", "pk")
        )

    @extend_schema(
        parameters=[KitchenFilterSerializer],
        responses={
            200: KitchenOrderSerializer(many=True),
            400: BAD_REQUEST,
            **DETAIL_ERRORS,
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
