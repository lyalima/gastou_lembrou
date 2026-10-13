from django.db import transaction
from django.utils import timezone

from .installments import add_months
from .models import Payment, PaymentRecurrence


@transaction.atomic
def configure_recurrence(payment, cleaned_data):
    Payment.objects.select_for_update().get(pk=payment.pk, user_id=payment.user_id)
    schedule = PaymentRecurrence.objects.filter(source=payment).first()
    if not cleaned_data.get("is_recurring"):
        if schedule:
            schedule.active = False
            schedule.save(update_fields=["active", "updated_at"])
        return
    if not schedule:
        schedule = PaymentRecurrence.objects.create(
            source=payment, interval_months=cleaned_data["recurrence_frequency"],
            anchor_date=payment.scheduled_date or payment.payment_date,
        )
    elif not schedule.active:
        schedule.active = True
        schedule.save(update_fields=["active", "updated_at"])
    generate_occurrences(schedule.pk)


@transaction.atomic
def generate_occurrences(schedule_id):
    from .tasks import queue_payment_confirmation

    schedule = PaymentRecurrence.objects.select_for_update().filter(pk=schedule_id, active=True).first()
    if not schedule:
        return 0
    source = schedule.source
    today = timezone.localdate()
    previous = add_months(schedule.anchor_date, (schedule.next_number - 1) * schedule.interval_months)
    if schedule.next_number > 1 and previous > today:
        return 0
    count = 0
    # Limit catch-up work per task while preserving the original day (including leap years).
    for _ in range(120):
        when = add_months(schedule.anchor_date, schedule.next_number * schedule.interval_months)
        payment, created = Payment.objects.get_or_create(
            recurrence=schedule, recurrence_number=schedule.next_number,
            defaults=dict(user=source.user, title=source.title, category=source.category,
                          description=source.description, kind=source.kind, amount=source.amount,
                          payment_method=source.payment_method, credit_card=source.credit_card,
                          payment_date=when, scheduled_date=when),
        )
        schedule.next_number += 1
        if created:
            count += 1
            if when >= today:
                transaction.on_commit(lambda pk=payment.pk: queue_payment_confirmation(pk))
        if when > today:
            break
    schedule.save(update_fields=["next_number", "updated_at"])
    return count
