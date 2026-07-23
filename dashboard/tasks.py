from datetime import date
from decimal import Decimal

from celery import shared_task
from django.db.models import Sum
from django.contrib.auth import get_user_model
from django.utils import timezone
from kombu.exceptions import OperationalError

from core.emails import send_branded_email
from payments.models import Payment

from .insights import build_insight_dataset, generate_insights
from .metrics import accountable_payments, filter_payments_by_report_month
from .models import FinancialInsightSnapshot, MonthlySpendingGoal, SpendingGoalNotification
from .reports import build_dashboard_report_pdf


def previous_month(reference_date=None):
    reference_date = reference_date or timezone.localdate()
    first_day = date(reference_date.year, reference_date.month, 1)
    last_day_previous_month = first_day - timezone.timedelta(days=1)
    return date(last_day_previous_month.year, last_day_previous_month.month, 1)


def queue_financial_insights(snapshot_id):
    try:
        generate_financial_insights.delay(snapshot_id)
    except OperationalError:
        generate_financial_insights(snapshot_id)


def queue_spending_goal_alert_check(user_id, month):
    try:
        check_spending_goal_alert.delay(user_id, month.strftime("%Y-%m"))
    except OperationalError:
        check_spending_goal_alert(user_id, month.strftime("%Y-%m"))


@shared_task
def generate_financial_insights(snapshot_id):
    snapshot = FinancialInsightSnapshot.objects.select_related("user").get(pk=snapshot_id)
    try:
        dataset = build_insight_dataset(snapshot.user, snapshot.period_key)
        result = generate_insights(dataset)
        snapshot.status = FinancialInsightSnapshot.Status.READY
        snapshot.source = result["source"]
        snapshot.summary = result["summary"]
        snapshot.insights = result["insights"]
        snapshot.error_message = ""
        snapshot.generated_at = timezone.now()
        snapshot.save(
            update_fields=[
                "status",
                "source",
                "summary",
                "insights",
                "error_message",
                "generated_at",
                "updated_at",
            ]
        )
    except Exception:
        snapshot.status = FinancialInsightSnapshot.Status.ERROR
        snapshot.error_message = "Não foi possível gerar os insights agora. Tente novamente."
        snapshot.save(update_fields=["status", "error_message", "updated_at"])


@shared_task
def check_spending_goal_alert(user_id, period_key):
    month = _parse_period_key(period_key)
    if not month:
        return False

    goal = MonthlySpendingGoal.objects.select_related("user").filter(user_id=user_id, period_month=month).first()
    if not goal or not goal.alert_threshold or not goal.user.email:
        return False

    payments = filter_payments_by_report_month(accountable_payments(Payment.objects.filter(user_id=user_id)), month)
    spent = payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
    if not goal.amount or goal.amount <= 0:
        return False

    percent = (spent / goal.amount) * Decimal("100")
    if percent < goal.alert_threshold:
        return False

    notification, created = SpendingGoalNotification.objects.get_or_create(
        goal=goal,
        period_key=period_key,
        threshold=goal.alert_threshold,
    )
    if not created:
        return False

    month_label = month.strftime("%m/%Y")
    send_branded_email(
        subject=f"Aviso de meta mensal de gastos: {goal.alert_threshold}% atingido - Gastou, Lembrou!",
        title=f"{goal.alert_threshold}% da meta atingida ",
        text_body=(
            f"Você atingiu {goal.alert_threshold}% da sua meta de gastos de {month_label}.\n\n"
            f"Meta definida: {_format_currency(goal.amount)}\n"
            f"Total registrado no mês: {_format_currency(spent)}\n\n"
            "Para mais informações acesse seu dashboard no sistema."
            "Obrigado por usar o Gastou, Lembrou!"
        ),
        to=[goal.user.email],
    )
    return True


@shared_task
def send_spending_goal_alerts():
    sent_count = 0
    goals = MonthlySpendingGoal.objects.select_related("user").filter(alert_threshold__isnull=False).exclude(user__email="")
    for goal in goals:
        if check_spending_goal_alert(goal.user_id, goal.period_month.strftime("%Y-%m")):
            sent_count += 1
    return sent_count


@shared_task
def send_previous_month_reports():
    report_month = previous_month()
    sent_count = 0
    User = get_user_model()
    users = User.objects.filter(is_active=True).exclude(email="")

    for user in users:
        user_payments = accountable_payments(Payment.objects.filter(user=user))
        if not filter_payments_by_report_month(user_payments, report_month).exists():
            continue

        pdf = build_dashboard_report_pdf(user, report_month)
        month_label = report_month.strftime("%m/%Y")
        filename = f"relatorio-gastou-lembrou-{report_month.strftime('%Y-%m')}.pdf"
        send_branded_email(
            subject=f"Seu relatório mensal do Gastou, Lembrou! - {month_label}",
            title="Relatório mensal disponível",
            text_body=(
                f"Olá! Seu relatório mensal referente a {month_label} está anexado a este email.\n\n"
                "Obrigado por usar o Gastou, Lembrou!"
            ),
            to=[user.email],
            attachments=[(filename, pdf, "application/pdf")],
        )
        sent_count += 1

    return sent_count


def _parse_period_key(period_key):
    try:
        year, month = [int(part) for part in period_key.split("-", 1)]
        return date(year, month, 1)
    except (TypeError, ValueError):
        return None


def _format_currency(value):
    return f"R$ {value:.2f}".replace(".", ",")
