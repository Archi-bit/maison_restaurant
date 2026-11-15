from datetime import date
from decimal import ROUND_HALF_UP

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
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


@extend_schema_serializer(component_name="ShiftAssignTable")
class AssignTableSerializer(serializers.Serializer):
    waiter_id = serializers.IntegerField(min_value=1, max_value=2**63 - 1)


class ReportDateField(serializers.DateField):
    def to_internal_value(self, value):
        parsed_date = super().to_internal_value(value)
        if isinstance(value, str) and value != parsed_date.isoformat():
            self.fail("invalid", format="YYYY-MM-DD")
        return parsed_date


class SalesPeriodSerializer(serializers.Serializer):
    date_from = ReportDateField(required=False, help_text="Первый день периода.")
    date_to = ReportDateField(required=False, help_text="Последний день периода включительно.")

    def validate(self, attrs):
        today = timezone.localdate(timezone=timezone.get_default_timezone())
        date_from = attrs.get("date_from", today)
        date_to = attrs.get("date_to", today)
        days = (date_to - date_from).days + 1
        if days < 1:
            raise serializers.ValidationError({"date_to": "Дата конца раньше даты начала."})
        if days > 366:
            raise serializers.ValidationError({"date_to": "Период не может превышать 366 дней."})
        # Оставляем место для предыдущего периода и смещения относительно UTC.
        if (date_from - date.min).days <= days:
            raise serializers.ValidationError({"date_from": "Дата начала слишком ранняя."})
        return {"date_from": date_from, "date_to": date_to}


class SalesSummarySerializer(serializers.Serializer):
    revenue = serializers.DecimalField(max_digits=None, decimal_places=2)
    paid_orders_count = serializers.IntegerField()
    average_check = serializers.DecimalField(
        max_digits=None, decimal_places=2, rounding=ROUND_HALF_UP
    )
    currency = serializers.ChoiceField(choices=["KGS"])


class PopularDishSerializer(serializers.Serializer):
    dish_id = serializers.IntegerField()
    dish_name = serializers.CharField()
    quantity = serializers.IntegerField()


class SalesChannelSerializer(serializers.Serializer):
    channel = serializers.CharField()
    paid_orders_count = serializers.IntegerField()
    revenue = serializers.DecimalField(max_digits=None, decimal_places=2)


class SalesComparisonSerializer(serializers.Serializer):
    current_revenue = serializers.DecimalField(max_digits=None, decimal_places=2)
    previous_revenue = serializers.DecimalField(max_digits=None, decimal_places=2)
    difference = serializers.DecimalField(max_digits=None, decimal_places=2)
    percent_change = serializers.DecimalField(
        max_digits=None, decimal_places=2, allow_null=True, rounding=ROUND_HALF_UP
    )
