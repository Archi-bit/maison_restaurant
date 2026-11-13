from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import RestaurantShift, ShiftEmployee, ShiftTableAssignment


class ShiftSerializer(serializers.ModelSerializer):
    class Meta:
        model = RestaurantShift
        fields = ("id", "status", "opened_at", "closed_at", "opened_by", "closed_by")
        read_only_fields = fields


@extend_schema_field({"type": "object", "nullable": True, "not": {"type": "object"}})
class NullShiftField(serializers.Field):
    pass


class NoCurrentShiftSerializer(serializers.Serializer):
    shift = NullShiftField()


class ShiftEmployeeSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="employee.full_name", read_only=True)
    role = serializers.CharField(source="employee.role", read_only=True)

    class Meta:
        model = ShiftEmployee
        fields = ("id", "employee", "full_name", "role", "added_at")
        read_only_fields = fields


class ShiftTableAssignmentSerializer(serializers.ModelSerializer):
    table_code = serializers.CharField(source="table.code", read_only=True)

    class Meta:
        model = ShiftTableAssignment
        fields = ("id", "table", "table_code", "waiter", "assigned_at")
        read_only_fields = fields


class AddShiftEmployeeSerializer(serializers.Serializer):
    employee_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)


class AssignTableSerializer(serializers.Serializer):
    waiter_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)
