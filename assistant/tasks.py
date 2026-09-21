from celery import shared_task

from .calendar import create_calendar_events_for_user


@shared_task
def create_calendar_events_task(user_id, payment_ids=None):
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if not user:
        return {"created": 0, "failed": 0}
    return create_calendar_events_for_user(user, payment_ids=payment_ids)
