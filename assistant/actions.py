from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.forms.models import model_to_dict
from django.utils import timezone

from payments.forms import PaymentForm
from payments.models import Payment
from payments.recurrences import configure_recurrence
from payments.installments import create_installment_siblings
from payments.tasks import queue_payment_confirmation

from .models import AssistantConversation, AssistantMessage, AssistantPaymentAction


ALLOWED_FIELDS = {"title", "amount", "description", "payment_date", "scheduled_date", "category", "payment_method", "credit_card", "is_installment", "installment_total", "installment_number", "is_recurring", "recurrence_frequency"}


def action_form(user, data, instance=None):
    initial = model_to_dict(instance, fields=PaymentForm._meta.fields) if instance else {"kind": Payment.Kind.EXPENSE}
    if instance:
        initial.pop("image", None)
        initial["amount"] = format(instance.amount, ".2f").replace(".", ",")
        schedule = getattr(instance, "recurring_schedule", None)
        if schedule and schedule.active:
            initial.update(is_recurring=True, recurrence_frequency=schedule.interval_months)
    initial.update(data)
    return PaymentForm(initial, instance=instance, user=user)


def propose_payment(user, conversation, operation, data, payment_id=""):
    if operation not in {"create", "update"} or not isinstance(data, dict) or not data or set(data) - ALLOWED_FIELDS:
        raise ValidationError("Informe apenas campos permitidos do pagamento.")
    if not conversation or conversation.user_id != user.pk or conversation.status != "active":
        raise ValidationError("Conversa encerrada.")
    data = dict(data)
    if "amount" in data:
        try:
            amount = Decimal(str(data["amount"]))
            if not amount.is_finite() or amount <= 0 or amount >= Decimal("1e18") or amount.as_tuple().exponent < -2:
                raise ValueError
            data["amount"] = format(amount, ".2f").replace(".", ",")
        except (ValueError, InvalidOperation):
            raise ValidationError("Informe um valor positivo em reais, com até duas casas decimais.") from None
    instance = None
    if operation == "update":
        try:
            instance = Payment.objects.get(pk=payment_id, user=user)
        except (Payment.DoesNotExist, ValidationError, ValueError):
            raise ValidationError("Pagamento não encontrado na sua conta.") from None
    form = action_form(user, data, instance)
    if not form.is_valid():
        raise ValidationError(form.errors.as_text())
    if operation == "create" and not (form.cleaned_data.get("payment_date") or form.cleaned_data.get("scheduled_date")):
        raise ValidationError("Informe a data de pagamento, de compra ou prevista para o gasto.")
    for field in data:
        value = form.cleaned_data[field]
        if isinstance(value, Decimal):
            value = format(value, ".2f").replace(".", ",")
        elif isinstance(value, date):
            value = value.isoformat()
        elif hasattr(value, "pk"):
            value = value.pk
        data[field] = value
    # Only a draft is created. This function never saves the payment form.
    with transaction.atomic():
        conversation.__class__.objects.select_for_update().get(pk=conversation.pk, user=user, status="active")
        AssistantPaymentAction.objects.filter(conversation=conversation, status="pending").update(status="cancelled")
        return AssistantPaymentAction.objects.create(
            user=user, conversation=conversation, operation=operation, payload=data,
            payment_id=instance.pk if instance else None,
            expected_updated_at=instance.updated_at if instance else None,
            expires_at=timezone.now() + timedelta(minutes=15),
        )


@transaction.atomic
def confirm_payment_action(user, action_id, decision):
    conversation_id = AssistantPaymentAction.objects.values_list("conversation_id", flat=True).get(pk=action_id, user=user)
    conversation = AssistantConversation.objects.select_for_update().get(pk=conversation_id, user=user)
    action = AssistantPaymentAction.objects.select_for_update().get(pk=action_id, user=user)
    if action.status != "pending":
        return action
    if decision == "cancel":
        action.status = "cancelled"
    else:
        if decision != "confirm" or action.expires_at <= timezone.now() or conversation.status != "active":
            raise ValidationError("Proposta expirada. Solicite uma nova proposta ao Spike.")
        instance = None
        if action.operation == "update":
            instance = Payment.objects.select_for_update().filter(pk=action.payment_id, user=user).first()
            if not instance or instance.updated_at != action.expected_updated_at:
                raise ValidationError("O pagamento foi alterado ou excluído. Solicite uma nova proposta.")
        form = action_form(user, action.payload, instance)
        if not form.is_valid():
            raise ValidationError("Os dados não são mais válidos. Solicite uma nova proposta.")
        form.instance.user = user
        payment = form.save()
        if action.operation == "create":
            create_installment_siblings(payment)
        configure_recurrence(payment, form.cleaned_data)
        if payment.scheduled_date:
            transaction.on_commit(lambda: queue_payment_confirmation(payment.pk))
        action.payment = payment
        action.status = "confirmed"
    action.save(update_fields=["status", "payment", "updated_at"])
    AssistantMessage.objects.create(user=user, conversation=conversation, role="assistant", intent="payment_action",
                                    content=f"Pagamento '{action.payment.title}' salvo após sua confirmação." if action.status == "confirmed" else "Proposta de alteração cancelada.")
    return action
