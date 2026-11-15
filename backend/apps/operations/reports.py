from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Sum
from django.utils import timezone

from apps.orders.models import Order, OrderItem


ZERO = Decimal("0.00")
ORDER_REVENUE = Sum(F("items__unit_price") * F("items__quantity"), default=ZERO)


def paid_orders(*, date_from, date_to):
    restaurant_timezone = timezone.get_default_timezone()
    start = datetime.combine(date_from, time.min, restaurant_timezone)
    end = datetime.combine(date_to, time.max, restaurant_timezone)
    return Order.objects.filter(is_paid=True, paid_at__range=(start, end)).exclude(
        status="cancelled"
    )


def sales_summary(orders):
    summary = orders.aggregate(
        paid_orders_count=Count("pk", distinct=True),
        revenue=ORDER_REVENUE,
    )
    count = summary["paid_orders_count"]
    summary["average_check"] = summary["revenue"] / count if count else ZERO
    summary["currency"] = "KGS"
    return summary


def popular_dishes(orders):
    dishes = (
        OrderItem.objects.filter(order__in=orders)
        .values("dish_id", "dish__name")
        .annotate(quantity=Sum("quantity"))
        .order_by("-quantity", "dish_id")[:10]
    )

    return [
        {
            "dish_id": dish["dish_id"],
            "dish_name": dish["dish__name"],
            "quantity": dish["quantity"],
        }
        for dish in dishes
    ]


def sales_channels(orders):
    sales_by_channel = {
        row["channel"]: row
        for row in orders.values("channel").annotate(
            paid_orders_count=Count("pk", distinct=True),
            revenue=ORDER_REVENUE,
        )
    }
    return [
        sales_by_channel.get(
            channel, {"channel": channel, "paid_orders_count": 0, "revenue": ZERO}
        )
        for channel, _ in Order.CHANNEL_CHOICES
    ]


def compare_sales(*, date_from, date_to):
    period_length = date_to - date_from + timedelta(days=1)
    current = paid_orders(date_from=date_from, date_to=date_to)
    previous = paid_orders(
        date_from=date_from - period_length, date_to=date_from - timedelta(days=1)
    )
    current_revenue = current.aggregate(revenue=ORDER_REVENUE)["revenue"]
    previous_revenue = previous.aggregate(revenue=ORDER_REVENUE)["revenue"]
    difference = current_revenue - previous_revenue
    return {
        "current_revenue": current_revenue,
        "previous_revenue": previous_revenue,
        "difference": difference,
        "percent_change": difference * 100 / previous_revenue if previous_revenue else None,
    }


def sales_rows(orders):
    restaurant_timezone = timezone.get_default_timezone()
    sales = orders.annotate(sales_total=ORDER_REVENUE).order_by("paid_at", "pk")
    for order in sales.iterator():
        yield (
            order.number,
            timezone.localtime(order.paid_at, restaurant_timezone).isoformat(),
            order.channel,
            f"{order.sales_total:.2f}",
            order.payment_method,
        )
