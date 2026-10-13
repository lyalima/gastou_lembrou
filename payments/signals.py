from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .cache import invalidate_user_payment_cache
from .classification import guess_payment_kind, normalize_text
from .models import Payment
from .tasks import queue_payment_categorization


@receiver(pre_save, sender=Payment)
def reuse_previous_category(sender, instance, **kwargs):
    if instance._state.adding and not instance.category_id:
        from django.db.models import Q
        from .models import Category
        from .categorization import historical_category_match
        categories = Category.objects.filter(Q(user__isnull=True) | Q(user_id=instance.user_id))
        instance.category = historical_category_match(instance, categories)


@receiver(pre_save, sender=Payment)
def assign_card_statement(sender, instance, **kwargs):
    from django.core.exceptions import ValidationError
    from .card_cycles import statement_due_date

    instance.statement_due_date = None
    if instance.credit_card_id:
        if instance.credit_card.user_id != instance.user_id:
            raise ValidationError("O cartão deve pertencer ao usuário do pagamento.")
        if instance.kind != Payment.Kind.CREDIT_CARD_BILL and normalize_text(getattr(instance.payment_method, "name", "")) not in {"cartao de credito", "cartao credito", "credito"}:
            instance.credit_card = None
        elif instance.payment_date or instance.scheduled_date:
            instance.statement_due_date = statement_due_date(instance.credit_card, instance.payment_date or instance.scheduled_date)
            if instance._state.adding and instance.installment_group and instance.installment_number:
                from .installments import add_months

                anchor = Payment.objects.filter(
                    user_id=instance.user_id,
                    credit_card_id=instance.credit_card_id,
                    installment_group=instance.installment_group,
                    statement_due_date__isnull=False,
                ).order_by("created_at").first()
                if anchor and anchor.installment_number:
                    instance.statement_due_date = add_months(
                        anchor.statement_due_date, instance.installment_number - anchor.installment_number
                    )
    if instance.credit_card_statement_id and instance.credit_card_statement.due_date:
        instance.statement_due_date = instance.credit_card_statement.due_date


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
    if not instance.is_installment:
        instance.installment_group = None
        instance.installment_number = None
        instance.installment_total = None


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

    from dashboard.metrics import spending_date_expression

    metric_date = Payment.objects.filter(pk=instance.pk).annotate(
        spending_date=spending_date_expression()
    ).values_list("spending_date", flat=True).get() or timezone.localdate()
    month = timezone.datetime(metric_date.year, metric_date.month, 1).date()
    transaction.on_commit(lambda: queue_spending_goal_alert_check(instance.user_id, month))
