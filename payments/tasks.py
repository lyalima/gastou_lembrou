from celery import shared_task
from django.db.models import Q
from django.utils import timezone
from kombu.exceptions import OperationalError

from core.emails import send_branded_email

from .categorization import choose_category_for_title
from .models import Category, Payment, PaymentNotification


def format_email_date(value):
    return value.strftime("%d/%m/%y")


def queue_payment_confirmation(payment_id):
    try:
        send_payment_confirmation.delay(str(payment_id))
    except OperationalError:
        send_payment_confirmation(str(payment_id))


def queue_payment_categorization(payment_id):
    try:
        categorize_payment.delay(str(payment_id))
    except OperationalError:
        return None


@shared_task
def categorize_payment(payment_id):
    payment = Payment.objects.filter(pk=payment_id).first()
    if not payment or payment.category_id:
        return

    categories = Category.objects.filter(Q(user__isnull=True) | Q(user=payment.user))
    category = choose_category_for_title(payment.title, categories)
    if category:
        Payment.objects.filter(pk=payment.pk, category__isnull=True).update(category=category)


@shared_task
def send_payment_confirmation(payment_id):
    payment = Payment.objects.select_related("user").get(pk=payment_id)
    if not payment.scheduled_date or not payment.user.email:
        return

    notification, created = PaymentNotification.objects.get_or_create(
        payment=payment,
        kind=PaymentNotification.Kind.SCHEDULED_CONFIRMATION,
        scheduled_date=payment.scheduled_date,
    )
    if not created:
        return

    send_branded_email(
        subject="Pagamento agendado no Gastou, Lembrou!",
        title="Pagamento agendado!",
        text_body=f'''O seu pagamento '{payment.title}' foi agendado para {format_email_date(payment.scheduled_date)}.\n
                    Obrigado por usar o Gastou, Lembrou!''',
        to=[payment.user.email],
    )


@shared_task
def send_payment_reminders():
    today = timezone.localdate()
    reminder_rules = (
        (
            1,
            PaymentNotification.Kind.REMINDER_1_DAY,
            lambda payment: f'''O seu pagamento '{payment.title}' no valor de R$ {payment.amount} vence amanhã. 
                            Não esqueça de pagar!\n
                            Obrigado por usar o Gastou, Lembrou!''',
        ),
        (
            0,
            PaymentNotification.Kind.REMINDER_DUE_TODAY,
            lambda payment: f'''O seu pagamento '{payment.title}' vence hoje. 
                            Não esqueça de pagar!\n
                            Obrigado por usar o Gastou, Lembrou!''',
        ),
    )

    for days, kind, build_message in reminder_rules:
        target_date = today + timezone.timedelta(days=days)
        payments = Payment.objects.select_related("user").filter(scheduled_date=target_date)
        for payment in payments:
            if not payment.user.email:
                continue

            notification, created = PaymentNotification.objects.get_or_create(
                payment=payment,
                kind=kind,
                scheduled_date=payment.scheduled_date,
            )
            if not created:
                continue

            send_branded_email(
                subject=f"Lembrete: {payment.title}",
                title="Lembrete de pagamento!",
                text_body=build_message(payment),
                to=[payment.user.email],
            )
