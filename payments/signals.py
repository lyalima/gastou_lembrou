from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .cache import invalidate_user_payment_cache
from .classification import guess_payment_kind, normalize_text
from .models import Payment
from .tasks import queue_payment_categorization


@receiver(pre_save, sender=Payment)
def sync_payment_date_with_scheduled_date(sender, instance, **kwargs):
    if instance.scheduled_date and not instance.payment_date:
        instance.payment_date = instance.scheduled_date


@receiver(pre_save, sender=Payment)
def classify_credit_card_bill(sender, instance, **kwargs):
    if instance.kind == Payment.Kind.EXPENSE and guess_payment_kind(instance.title, instance.category) == Payment.Kind.CREDIT_CARD_BILL:
        instance.kind = Payment.Kind.CREDIT_CARD_BILL


@receiver(pre_save, sender=Payment)
def clear_installment_for_non_credit_card(sender, instance, **kwargs):
    method_name = getattr(instance.payment_method, "name", "")
    if normalize_text(method_name) not in {"cartao de credito", "cartao credito", "credito"}:
        instance.is_installment = False


@receiver(post_save, sender=Payment)
def invalidate_payment_cache_after_save(sender, instance, **kwargs):
    transaction.on_commit(lambda: invalidate_user_payment_cache(instance.user_id))


@receiver(post_delete, sender=Payment)
def invalidate_payment_cache_after_delete(sender, instance, **kwargs):
    transaction.on_commit(lambda: invalidate_user_payment_cache(instance.user_id))


@receiver(post_save, sender=Payment)
def categorize_uncategorized_payment(sender, instance, created, **kwargs):
    if created and not instance.category_id:
        transaction.on_commit(lambda: queue_payment_categorization(instance.pk))


@receiver(post_save, sender=Payment)
def check_spending_goal_after_payment_save(sender, instance, **kwargs):
    from dashboard.tasks import queue_spending_goal_alert_check

    metric_date = instance.payment_date or instance.scheduled_date or timezone.localdate()
    month = timezone.datetime(metric_date.year, metric_date.month, 1).date()
    transaction.on_commit(lambda: queue_spending_goal_alert_check(instance.user_id, month))
