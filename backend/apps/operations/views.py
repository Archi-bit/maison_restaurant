import csv

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.reservations.models import RestaurantTable
from apps.staff.models import EmployeeProfile
from apps.staff.permissions import (
    HasEmployeeProfile,
    IsAssignedWaiter,
    IsOwnerOrAdministrator,
    get_employee_profile,
)

from . import reports
from .models import RestaurantShift
from .serializers import (
    AddShiftEmployeeSerializer,
    AssignTableSerializer,
    NoCurrentShiftSerializer,
    PopularDishSerializer,
    SalesChannelSerializer,
    SalesComparisonSerializer,
    SalesPeriodSerializer,
    SalesSummarySerializer,
    ShiftEmployeeSerializer,
    ShiftSerializer,
    ShiftTableAssignmentSerializer,
)
from .services import (
    OperationBusinessError,
    add_shift_employee,
    assign_shift_table,
    close_shift,
    get_current_shift,
    get_shift_tables,
    get_waiter_tables,
    open_shift,
)


AUTH_ERRORS = {
    401: OpenApiResponse(description="Требуется действующий JWT."),
    403: OpenApiResponse(description="У сотрудника нет прав на эту операцию."),
}
NOT_FOUND = OpenApiResponse(description="Смена, сотрудник или стол не найдены.")
INVALID_OPERATION = OpenApiResponse(
    description="Некорректные данные или нарушено правило операции."
)


class ShiftManagementView(APIView):
    permission_classes = [IsOwnerOrAdministrator]

    def handle_exception(self, exc):
        if isinstance(exc, OperationBusinessError):
            return Response(
                {"code": exc.code, "detail": exc.message},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().handle_exception(exc)


class OpenShiftView(ShiftManagementView):
    @extend_schema(
        summary="Открыть смену",
        request=None,
        responses={201: ShiftSerializer, 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def post(self, request):
        shift = open_shift(actor=get_employee_profile(request.user))
        return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


class CloseShiftView(ShiftManagementView):
    @extend_schema(
        summary="Закрыть смену",
        request=None,
        responses={200: ShiftSerializer, 400: INVALID_OPERATION, 404: NOT_FOUND, **AUTH_ERRORS},
    )
    def post(self, request, id):
        shift = get_object_or_404(RestaurantShift, pk=id)
        shift = close_shift(shift=shift, actor=get_employee_profile(request.user))
        return Response(ShiftSerializer(shift).data)


class CurrentShiftView(APIView):
    permission_classes = [HasEmployeeProfile]

    @extend_schema(
        summary="Получить текущую смену",
        responses={
            200: PolymorphicProxySerializer(
                component_name="CurrentShift",
                serializers=[ShiftSerializer, NoCurrentShiftSerializer],
                resource_type_field_name=None,
            ),
            **AUTH_ERRORS,
        },
    )
    def get(self, request):
        shift = get_current_shift()
        if shift is None:
            return Response({"shift": None})
        return Response(ShiftSerializer(shift).data)


class ShiftEmployeesView(ShiftManagementView):
    @extend_schema(
        summary="Получить состав смены",
        responses={200: ShiftEmployeeSerializer(many=True), 404: NOT_FOUND, **AUTH_ERRORS},
    )
    def get(self, request, id):
        shift = get_object_or_404(RestaurantShift, pk=id)
        employees = shift.employees.select_related("employee").order_by("id")
        return Response(ShiftEmployeeSerializer(employees, many=True).data)

    @extend_schema(
        summary="Добавить сотрудника в смену",
        request=AddShiftEmployeeSerializer,
        responses={
            201: ShiftEmployeeSerializer, 400: INVALID_OPERATION,
            404: NOT_FOUND, **AUTH_ERRORS,
        },
    )
    def post(self, request, id):
        shift = get_object_or_404(RestaurantShift, pk=id)
        serializer = AddShiftEmployeeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        employee = get_object_or_404(
            EmployeeProfile.objects.select_related("user"),
            pk=serializer.validated_data["employee_id"],
        )
        shift_employee = add_shift_employee(
            shift=shift, employee=employee, actor=get_employee_profile(request.user)
        )
        return Response(
            ShiftEmployeeSerializer(shift_employee).data, status=status.HTTP_201_CREATED
        )


class AssignTableView(ShiftManagementView):
    @extend_schema(
        summary="Закрепить стол или сменить официанта",
        request=AssignTableSerializer,
        responses={
            200: ShiftTableAssignmentSerializer, 201: ShiftTableAssignmentSerializer,
            400: INVALID_OPERATION, 404: NOT_FOUND, **AUTH_ERRORS,
        },
    )
    def put(self, request, id, table_id):
        shift = get_object_or_404(RestaurantShift, pk=id)
        table = get_object_or_404(RestaurantTable, pk=table_id)
        serializer = AssignTableSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        waiter = get_object_or_404(
            EmployeeProfile.objects.select_related("user"),
            pk=serializer.validated_data["waiter_id"],
        )
        assignment, created = assign_shift_table(
            shift=shift, table=table, waiter=waiter, actor=get_employee_profile(request.user)
        )
        response_status = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(ShiftTableAssignmentSerializer(assignment).data, status=response_status)


class CurrentShiftTablesView(APIView):
    permission_classes = [IsOwnerOrAdministrator | IsAssignedWaiter]

    @extend_schema(
        summary="Получить назначения столов в текущей смене",
        responses={200: ShiftTableAssignmentSerializer(many=True), **AUTH_ERRORS},
    )
    def get(self, request):
        shift = get_current_shift()
        if shift is None:
            return Response([])
        employee = get_employee_profile(request.user)
        if employee.role == EmployeeProfile.Role.WAITER:
            assignments = get_waiter_tables(shift=shift, waiter=employee)
        else:
            assignments = get_shift_tables(shift=shift)
        return Response(ShiftTableAssignmentSerializer(assignments, many=True).data)


class SalesReportView(APIView):
    permission_classes = [IsOwnerOrAdministrator]

    def get_period(self, request):
        serializer = SalesPeriodSerializer(data=request.query_params.dict())
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_paid_orders(self, request):
        return reports.paid_orders(**self.get_period(request))


class SalesSummaryView(SalesReportView):
    @extend_schema(
        summary="Выручка, число оплаченных заказов и средний чек",
        parameters=[SalesPeriodSerializer],
        responses={200: SalesSummarySerializer, 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def get(self, request):
        summary = reports.sales_summary(self.get_paid_orders(request))
        return Response(SalesSummarySerializer(summary).data)


class PopularDishesView(SalesReportView):
    @extend_schema(
        summary="Десять самых продаваемых блюд",
        parameters=[SalesPeriodSerializer],
        responses={200: PopularDishSerializer(many=True), 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def get(self, request):
        dishes = reports.popular_dishes(self.get_paid_orders(request))
        return Response(PopularDishSerializer(dishes, many=True).data)


class SalesChannelsView(SalesReportView):
    @extend_schema(
        summary="Продажи по каналам заказа",
        parameters=[SalesPeriodSerializer],
        responses={200: SalesChannelSerializer(many=True), 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def get(self, request):
        channels = reports.sales_channels(self.get_paid_orders(request))
        return Response(SalesChannelSerializer(channels, many=True).data)


class SalesComparisonView(SalesReportView):
    @extend_schema(
        summary="Сравнить выручку с предыдущим периодом",
        parameters=[SalesPeriodSerializer],
        responses={200: SalesComparisonSerializer, 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def get(self, request):
        comparison = reports.compare_sales(**self.get_period(request))
        return Response(SalesComparisonSerializer(comparison).data)


class SalesCSVRenderer(JSONRenderer):
    media_type = "text/csv"
    format = "csv"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        # Успешный ответ формируется в HttpResponse, ошибки DRF остаются в JSON.
        renderer_context["response"]["Content-Type"] = "application/json"
        return super().render(data, accepted_media_type, renderer_context)


class SalesCSVView(SalesReportView):
    renderer_classes = [JSONRenderer, SalesCSVRenderer]

    @extend_schema(
        operation_id="v1_staff_reports_sales_csv_retrieve",
        summary="Скачать продажи в CSV",
        parameters=[SalesPeriodSerializer, OpenApiParameter("format", exclude=True)],
        responses={(200, "text/csv"): OpenApiTypes.STR, 400: INVALID_OPERATION, **AUTH_ERRORS},
    )
    def get(self, request):
        orders = self.get_paid_orders(request)
        response = HttpResponse(
            content_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="sales.csv"'},
        )
        writer = csv.writer(response)
        writer.writerow(("order_number", "paid_at", "channel", "total", "payment_method"))
        writer.writerows(reports.sales_rows(orders))
        return response
