from datetime import time

from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.generics import GenericAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reservations.models import Reservation, ReservationHistory, RestaurantTable
from apps.reservations.services import (
    ReservationBusinessError,
    assign_table,
    cancel_reservation,
    confirm_reservation,
    create_public_reservation,
    create_staff_reservation,
    get_hall_plan,
    mark_arrived,
    update_reservation,
)
from apps.staff.models import EmployeeProfile
from apps.staff.permissions import (
    HasEmployeeProfile,
    IsAssignedWaiter,
    IsOwnerOrAdministrator,
)
from .serializers import (
    ApiErrorSerializer,
    AssignTableSerializer,
    HallPlanQuerySerializer,
    HallPlanResponseSerializer,
    NoPayloadSerializer,
    PublicReservationCreateSerializer,
    PublicReservationResponseSerializer,
    ReservationHistorySerializer,
    StaffReservationCreateSerializer,
    StaffReservationDetailSerializer,
    StaffReservationListQuerySerializer,
    StaffReservationListSerializer,
    StaffReservationUpdateSerializer,
)


class ReservationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _read_permissions():
    return [
        HasEmployeeProfile(),
        (IsOwnerOrAdministrator | IsAssignedWaiter)(),
    ]


def _write_permissions():
    return [HasEmployeeProfile(), IsOwnerOrAdministrator()]


def _call_service(service, **kwargs):
    try:
        return service(**kwargs), None
    except ReservationBusinessError as exc:
        return None, Response(
            {"code": exc.code, "detail": exc.message},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _reservation_queryset(employee):
    queryset = Reservation.objects.select_related(
        "table", "responsible_employee", "created_by"
    )
    if employee.role == EmployeeProfile.Role.WAITER:
        return queryset.filter(responsible_employee=employee)
    return queryset


def _employee(request):
    return request.user.employee_profile


class PublicReservationCreateView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(
        request=PublicReservationCreateSerializer,
        responses={
            201: PublicReservationResponseSerializer,
            400: ApiErrorSerializer,
        },
        description="Отправить публичную заявку на бронирование.",
    )
    def post(self, request):
        serializer = PublicReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation, error = _call_service(
            create_public_reservation,
            validated_data=serializer.validated_data,
        )
        if error:
            return error

        return Response(
            {
                "id": reservation.pk,
                "reservation_number": reservation.number,
                "status": reservation.status,
                "message": "Спасибо за заявку. Мы свяжемся с вами для подтверждения.",
            },
            status=status.HTTP_201_CREATED,
        )


class StaffReservationListCreateView(GenericAPIView):
    pagination_class = ReservationPagination
    permission_classes = [HasEmployeeProfile]

    def get_permissions(self):
        if self.request.method == "GET":
            return _read_permissions()
        return _write_permissions()

    @extend_schema(
        operation_id="staff_reservations_list",
        parameters=[
            OpenApiParameter("date", OpenApiTypes.DATE, description="Дата брони"),
            OpenApiParameter("status", OpenApiTypes.STR, description="Статус брони"),
            OpenApiParameter("search", OpenApiTypes.STR, description="Имя или телефон"),
            OpenApiParameter("page", OpenApiTypes.INT, description="Номер страницы"),
            OpenApiParameter("page_size", OpenApiTypes.INT, description="Размер страницы (до 100)"),
        ],
        responses={200: inline_serializer(
            name="StaffReservationPage",
            fields={
                "count": serializers.IntegerField(),
                "next": serializers.URLField(allow_null=True),
                "previous": serializers.URLField(allow_null=True),
                "results": StaffReservationListSerializer(many=True),
            },
        ), 400: ApiErrorSerializer},
    )
    def get(self, request):
        query_serializer = StaffReservationListQuerySerializer(
            data=request.query_params
        )
        query_serializer.is_valid(raise_exception=True)
        filters = query_serializer.validated_data

        queryset = _reservation_queryset(_employee(request)).order_by(
            "-date", "-start_time", "-pk"
        )
        if "date" in filters:
            queryset = queryset.filter(date=filters["date"])
        if "status" in filters:
            queryset = queryset.filter(status=filters["status"])
        search = filters.get("search")
        if search:
            queryset = queryset.filter(
                Q(guest_name__icontains=search) | Q(phone__icontains=search)
            )

        page = self.paginate_queryset(queryset)
        serializer = StaffReservationListSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        request=StaffReservationCreateSerializer,
        responses={
            201: StaffReservationDetailSerializer,
            400: ApiErrorSerializer,
        },
    )
    def post(self, request):
        serializer = StaffReservationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation, error = _call_service(
            create_staff_reservation,
            validated_data=serializer.validated_data,
            actor=_employee(request),
        )
        if error:
            return error
        return Response(
            StaffReservationDetailSerializer(reservation).data,
            status=status.HTTP_201_CREATED,
        )


class StaffReservationDetailView(GenericAPIView):
    permission_classes = [HasEmployeeProfile]
    queryset = Reservation.objects.all()

    def get_permissions(self):
        if self.request.method == "GET":
            return _read_permissions()
        return _write_permissions()

    def get_object(self):
        queryset = _reservation_queryset(_employee(self.request))
        return get_object_or_404(queryset, pk=self.kwargs["id"])

    @extend_schema(
        operation_id="staff_reservations_retrieve",
        responses={200: StaffReservationDetailSerializer},
    )
    def get(self, request, id):
        reservation = self.get_object()
        return Response(StaffReservationDetailSerializer(reservation).data)

    @extend_schema(
        request=StaffReservationUpdateSerializer,
        responses={
            200: StaffReservationDetailSerializer,
            400: ApiErrorSerializer,
        },
    )
    def patch(self, request, id):
        reservation = self.get_object()
        serializer = StaffReservationUpdateSerializer(
            data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated, error = _call_service(
            update_reservation,
            reservation=reservation,
            validated_data=serializer.validated_data,
            actor=_employee(request),
        )
        if error:
            return error
        return Response(StaffReservationDetailSerializer(updated).data)


class ReservationActionView(APIView):
    permission_classes = [HasEmployeeProfile]
    service = None

    def get_permissions(self):
        return _write_permissions()

    def post(self, request, id):
        serializer = NoPayloadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = _reservation_queryset(_employee(request)).filter(
            pk=id
        ).first()
        if reservation is None:
            return Response(
                {"detail": "Бронирование не найдено."},
                status=status.HTTP_404_NOT_FOUND,
            )
        updated, error = _call_service(
            self.service, reservation=reservation, actor=_employee(request)
        )
        if error:
            return error
        return Response(StaffReservationDetailSerializer(updated).data)


class ConfirmReservationView(ReservationActionView):
    service = staticmethod(confirm_reservation)

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: StaffReservationDetailSerializer, 400: ApiErrorSerializer},
    )
    def post(self, request, id):
        return super().post(request, id)


class ArriveReservationView(ReservationActionView):
    service = staticmethod(mark_arrived)

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: StaffReservationDetailSerializer, 400: ApiErrorSerializer},
    )
    def post(self, request, id):
        return super().post(request, id)


class CancelReservationView(ReservationActionView):
    service = staticmethod(cancel_reservation)

    @extend_schema(
        request=NoPayloadSerializer,
        responses={200: StaffReservationDetailSerializer, 400: ApiErrorSerializer},
    )
    def post(self, request, id):
        return super().post(request, id)


class AssignTableView(APIView):
    permission_classes = [HasEmployeeProfile]

    def get_permissions(self):
        return _write_permissions()

    @extend_schema(
        request=AssignTableSerializer,
        responses={200: StaffReservationDetailSerializer, 400: ApiErrorSerializer},
    )
    def post(self, request, id):
        serializer = AssignTableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        reservation = _reservation_queryset(_employee(request)).filter(
            pk=id
        ).first()
        if reservation is None:
            return Response(
                {"detail": "Бронирование не найдено."},
                status=status.HTTP_404_NOT_FOUND,
            )
        table = RestaurantTable.objects.filter(
            pk=serializer.validated_data["table_id"]
        ).first()
        updated, error = _call_service(
            assign_table,
            reservation=reservation,
            table=table,
            actor=_employee(request),
        )
        if error:
            return error
        return Response(StaffReservationDetailSerializer(updated).data)


class ReservationHistoryView(APIView):
    permission_classes = [HasEmployeeProfile]

    def get_permissions(self):
        return _read_permissions()

    @extend_schema(responses={200: ReservationHistorySerializer(many=True)})
    def get(self, request, id):
        reservation = _reservation_queryset(_employee(request)).filter(
            pk=id
        ).first()
        if reservation is None:
            return Response(
                {"detail": "Бронирование не найдено."},
                status=status.HTTP_404_NOT_FOUND,
            )
        history = ReservationHistory.objects.filter(
            reservation=reservation
        ).select_related("actor").order_by("created_at", "pk")
        return Response(ReservationHistorySerializer(history, many=True).data)


def _safe_reservation_summary(raw_reservation):
    if not isinstance(raw_reservation, dict):
        return None
    return {
        key: raw_reservation[key]
        for key in (
            "reservation_number", "number", "guest_name", "guests_count",
            "start_time", "end_time",
        )
        if key in raw_reservation
    }


def _employee_id(raw_reservation):
    if not isinstance(raw_reservation, dict):
        return None
    employee_id = raw_reservation.get("responsible_employee_id")
    if employee_id is not None:
        return employee_id
    responsible_employee = raw_reservation.get("responsible_employee")
    if isinstance(responsible_employee, dict):
        return responsible_employee.get("id")
    return getattr(responsible_employee, "pk", None)


def _safe_hall_plan(plan, employee):
    is_manager = employee.role in (
        EmployeeProfile.Role.OWNER,
        EmployeeProfile.Role.ADMINISTRATOR,
    )
    tables = []
    for raw_table in plan.get("tables", []):
        reservation = None
        linked_reservations = raw_table.get(
            "reservations", raw_table.get("reservation", [])
        )
        if isinstance(linked_reservations, dict):
            linked_reservations = [linked_reservations]
        for raw_reservation in linked_reservations or []:
            if is_manager or _employee_id(raw_reservation) == employee.pk:
                reservation = _safe_reservation_summary(raw_reservation)
                if reservation:
                    break
        tables.append({
            "id": raw_table["id"],
            "code": raw_table["code"],
            "capacity": raw_table["capacity"],
            "zone": raw_table["zone"],
            "is_active": raw_table["is_active"],
            "status": raw_table["status"],
            "reservation": reservation,
        })

    raw_time = plan["time"]
    if isinstance(raw_time, time):
        plan_time = raw_time
    else:
        plan_time = time.fromisoformat(str(raw_time))
    return {
        "date": plan["date"],
        "time": plan_time.strftime("%H:%M"),
        "duration_minutes": plan["duration_minutes"],
        "tables": tables,
    }


class HallPlanView(APIView):
    permission_classes = [HasEmployeeProfile]

    def get_permissions(self):
        return _read_permissions()

    @extend_schema(
        parameters=[
            OpenApiParameter("date", OpenApiTypes.DATE, required=False),
            OpenApiParameter("time", OpenApiTypes.TIME, required=False),
            OpenApiParameter("duration_minutes", OpenApiTypes.INT, required=False),
        ],
        responses={200: HallPlanResponseSerializer, 400: ApiErrorSerializer},
        description="Безопасный план зала без телефонов и заметок гостей.",
    )
    def get(self, request):
        serializer = HallPlanQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        plan, error = _call_service(
            get_hall_plan,
            date=serializer.validated_data.get("date"),
            time=serializer.validated_data.get("time"),
            duration_minutes=serializer.validated_data.get("duration_minutes"),
        )
        if error:
            return error
        safe_plan = _safe_hall_plan(plan, _employee(request))
        return Response(safe_plan)
