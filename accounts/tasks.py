from celery import shared_task
from django.contrib.auth import get_user_model
from kombu.exceptions import OperationalError

from core.emails import send_branded_email

from .legal import PRIVACY_VERSION, TERMS_VERSION, needs_legal_update_acceptance
from .models import LegalUpdateNotification


def queue_legal_update_notification(user_id):
    try:
        send_legal_update_notification.delay(str(user_id))
    except OperationalError:
        send_legal_update_notification(str(user_id))


@shared_task
def send_legal_update_notification(user_id):
    User = get_user_model()
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user or not user.email or not needs_legal_update_acceptance(user):
        return False

    notification_filter = {
        "user": user,
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
    }
    if LegalUpdateNotification.objects.filter(**notification_filter).exists():
        return False

    send_branded_email(
        subject="Atualização dos Termos de Uso e Política de Privacidade - Gastou, Lembrou!",
        title="Atualização dos Termos de Uso e Política de Privacidade",
        text_body=(
            "Olá!\n"
            "Estamos enviando este email para informar que atualizamos nossos Termos de Uso e Política de Privacidade."
            "Essa atualização foi feita para refletir novas funcionalidades, incluindo importação de extratos bancários, "
            "importação de faturas de cartão em PDF e armazenamento dos arquivos enviados para execução do serviço.\n"
            "No próximo acesso ao sistema, será solicitado que você leia e aceite a versão atualizada dos termos para continuar usando o sistema.\n"
            "Obrigado por usar o Gastou, Lembrou!"
        ),
        to=[user.email],
    )

    _, created = LegalUpdateNotification.objects.get_or_create(**notification_filter)
    return created


@shared_task
def send_pending_legal_update_notifications():
    User = get_user_model()
    sent_count = 0
    users = User.objects.filter(is_active=True).exclude(email="")
    for user in users.iterator():
        if not needs_legal_update_acceptance(user):
            continue
        if send_legal_update_notification(str(user.pk)):
            sent_count += 1
    return sent_count
