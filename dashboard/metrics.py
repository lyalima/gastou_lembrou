from datetime import date

from django.db.models import Case, Count, F, Q, Sum, When
from django.db.models.functions import Coalesce, TruncDay, TruncMonth
from django.utils import timezone

from payments.models import Payment


def get_dashboard_metrics(user, month=None):
    payments = accountable_payments(Payment.objects.filter(user=user)).select_related("category", "payment_method", "credit_card")
    if month:
        payments = filter_payments_by_report_month(payments, month)

    by_category = (
        payments.values("category__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("category__name")
    )
    evolution_trunc = TruncDay("metric_date") if month else TruncMonth("metric_date")
    evolution_date_format = "%d/%m/%Y" if month else "%m/%Y"
    by_period = (
        payments.annotate(metric_date=activity_date_expression())
        .exclude(metric_date__isnull=True)
        .annotate(period=evolution_trunc)
        .values("period")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("period")
    )
    by_payment_method = (
        payments.values("payment_method__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by(F("payment_method__name").asc(nulls_first=True))
    )

    category_metrics = [
        {
            "name": item["category__name"] or "Sem categoria",
            "total": item["total"] or 0,
            "count": item["count"],
        }
        for item in by_category
    ]
    period_metrics = [
        {
            "name": item["period"].strftime(evolution_date_format),
            "total": item["total"] or 0,
            "count": item["count"],
        }
        for item in by_period
    ]
    payment_method_metrics = [
        {
            "name": item["payment_method__name"] or "Sem forma",
            "total": item["total"] or 0,
            "count": item["count"],
        }
        for item in by_payment_method
    ]

    return {
        "payments": payments,
        "total": payments.aggregate(total=Sum("amount"))["total"] or 0,
        "payment_count": payments.count(),
        "scheduled_count": payments.exclude(scheduled_date__isnull=True).count(),
        "category_metrics": category_metrics,
        "category_labels": [item["name"] for item in category_metrics],
        "category_totals": [float(item["total"]) for item in category_metrics],
        "month_metrics": period_metrics,
        "month_labels": [item["name"] for item in period_metrics],
        "month_totals": [float(item["total"]) for item in period_metrics],
        "evolution_title": "Evolução ao longo do mês" if month else "Evolução mensal",
        "payment_method_metrics": payment_method_metrics,
        "payment_method_labels": [item["name"] for item in payment_method_metrics],
        "payment_method_totals": [float(item["total"]) for item in payment_method_metrics],
        "recent_payments": payments.order_by("-created_at")[:5],
        "report_payments": payments.annotate(metric_date=activity_date_expression()).order_by("metric_date", "created_at", "pk"),
    }


def get_available_report_months(user):
    months = (
        accountable_payments(Payment.objects.filter(user=user))
        .annotate(metric_date=spending_date_expression())
        .exclude(metric_date__isnull=True)
        .annotate(month=TruncMonth("metric_date"))
        .values_list("month", flat=True)
        .distinct()
        .order_by("-month")
    )
    return [{"value": item.strftime("%Y-%m"), "label": item.strftime("%m/%Y")} for item in months]


def parse_report_month(value):
    if not value:
        return None
    try:
        year, month = [int(part) for part in value.split("-", 1)]
        return date(year, month, 1)
    except (TypeError, ValueError):
        return None


def default_report_month(user):
    available_months = get_available_report_months(user)
    if available_months:
        return parse_report_month(available_months[0]["value"])
    today = timezone.localdate()
    return date(today.year, today.month, 1)


def filter_payments_by_report_month(queryset, month):
    return queryset.annotate(metric_date=spending_date_expression()).filter(
        metric_date__year=month.year, metric_date__month=month.month
    )


def activity_date_expression():
    # payment_date stores the purchase date for credit-card expenses.
    return spending_date_expression()


def spending_date_expression():
    credit = Q(statement_due_date__isnull=False)
    for name in ("Cartão de crédito", "Cartao de credito", "Cartão crédito", "Credito", "Crédito"):
        credit |= Q(payment_method__name__iexact=name)
    return Case(
        When(credit, then=Coalesce("payment_date", "scheduled_date")),
        default=Coalesce("scheduled_date", "payment_date"),
    )


def spending_payments(user_id, month=None):
    payments = accountable_payments(Payment.objects.filter(user_id=user_id))
    if month:
        payments = payments.annotate(spending_date=spending_date_expression()).filter(
            spending_date__year=month.year, spending_date__month=month.month,
        )
    return payments


def get_spending_summary(user_id, month=None):
    return spending_payments(user_id, month).aggregate(
        total=Coalesce(Sum("amount"), 0, output_field=Payment._meta.get_field("amount")),
        payment_count=Count("pk"),
        scheduled_count=Count("pk", filter=Q(scheduled_date__isnull=False)),
    )


def accountable_payments(queryset):
    return queryset.filter(kind=Payment.Kind.EXPENSE)
