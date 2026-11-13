from django.shortcuts import get_object_or_404
from drf_spectacular.utils import (
    OpenApiResponse,
    PolymorphicProxySerializer,
    extend_schema,
)
from rest_framework import status
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

from .models import RestaurantShift
from .serializers import (
    AddShiftEmployeeSerializer,
    AssignTableSerializer,
    NoCurrentShiftSerializer,
    ShiftEmployeeSerializer,
    ShiftSerializer,
    ShiftTableAssignmentSerializer,
)
from .services import (
    OperationBusinessError,
    add_shift_employee,
    assign_shift_table,
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
        summary="Закрепить стол за официантом",
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
