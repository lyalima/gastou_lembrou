from datetime import timedelta
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.core import signing
from django.urls import reverse
from django.utils import timezone

from payments.models import Payment

from .models import GoogleCalendarConnection, PaymentCalendarEvent


CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.events"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
MAX_EVENTS_PER_CONFIRMATION = 20


class GoogleCalendarConnectionError(Exception):
    pass


def google_calendar_configured():
    google_app = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get("APP", {})
    return bool(google_app.get("client_id") and google_app.get("secret"))


def build_google_calendar_auth_url(request):
    google_app = settings.SOCIALACCOUNT_PROVIDERS["google"]["APP"]
    state = signing.dumps({"user_id": str(request.user.pk)}, salt="google-calendar-oauth")
    params = {
        "client_id": google_app["client_id"],
        "redirect_uri": request.build_absolute_uri(reverse("assistant:calendar_callback")),
        "response_type": "code",
        "scope": CALENDAR_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_calendar_code(request, code):
    google_app = settings.SOCIALACCOUNT_PROVIDERS["google"]["APP"]
    response = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": google_app["client_id"],
            "client_secret": google_app["secret"],
            "redirect_uri": request.build_absolute_uri(reverse("assistant:calendar_callback")),
            "grant_type": "authorization_code",
        },
        timeout=20,
    )
    if not response.ok:
        raise GoogleCalendarConnectionError(_google_error_message(response, "token"))
    payload = response.json()
    access_token = payload["access_token"]
    connection, _ = GoogleCalendarConnection.objects.get_or_create(user=request.user)
    connection.access_token = access_token
    if payload.get("refresh_token"):
        connection.refresh_token = payload["refresh_token"]
    connection.google_email = request.user.email
    connection.scope = payload.get("scope", CALENDAR_SCOPE)
    connection.token_expires_at = timezone.now() + timedelta(seconds=payload.get("expires_in", 3600))
    connection.is_active = True
    connection.save()
    return connection


def _google_error_message(response, step):
    try:
        payload = response.json()
    except ValueError:
        return f"Falha no Google OAuth durante {step}: HTTP {response.status_code}."
    error = payload.get("error", "erro_desconhecido")
    description = payload.get("error_description") or payload.get("error_uri") or ""
    return f"Falha no Google OAuth durante {step}: {error}. {description}".strip()


def validate_calendar_state(request, state):
    try:
        data = signing.loads(state, salt="google-calendar-oauth", max_age=600)
    except signing.BadSignature:
        return False
    return str(data.get("user_id")) == str(request.user.pk)


def calendar_candidate_payments(user, payment_ids=None):
    today = timezone.localdate()
    payments = (
        Payment.objects.filter(user=user, scheduled_date__gte=today)
        .exclude(calendar_event__status=PaymentCalendarEvent.Status.CREATED)
        .select_related("category", "payment_method")
        .order_by("scheduled_date", "title")
    )
    if payment_ids is not None:
        payments = payments.filter(pk__in=payment_ids)
    return payments[:MAX_EVENTS_PER_CONFIRMATION]


def build_event_proposals(user, payment_ids=None):
    payments = calendar_candidate_payments(user, payment_ids=payment_ids)
    proposals = []
    for payment in payments:
        event_date = payment.scheduled_date
        if not event_date:
            continue
        proposals.append(
            {
                "payment": payment,
                "date": event_date,
                "title": f"Pagar {payment.title}",
                "description": _event_description(payment),
            }
        )
    return proposals


def create_calendar_events_for_user(user, payment_ids=None):
    connection = getattr(user, "google_calendar_connection", None)
    if not connection or not connection.is_active:
        return {"created": 0, "failed": 0}
    access_token = ensure_access_token(connection)
    created = 0
    failed = 0
    for proposal in build_event_proposals(user, payment_ids=payment_ids):
        payment = proposal["payment"]
        event, event_created = PaymentCalendarEvent.objects.get_or_create(
            user=user,
            payment=payment,
            defaults={
                "title": proposal["title"],
                "scheduled_for": proposal["date"],
                "status": PaymentCalendarEvent.Status.FAILED,
            },
        )
        if not event_created and event.status == PaymentCalendarEvent.Status.CREATED:
            continue
        try:
            google_event_id = create_google_calendar_event(access_token, proposal)
            event.google_event_id = google_event_id
            event.title = proposal["title"]
            event.scheduled_for = proposal["date"]
            event.status = PaymentCalendarEvent.Status.CREATED
            event.error_message = ""
            event.save(update_fields=["google_event_id", "title", "scheduled_for", "status", "error_message", "updated_at"])
            created += 1
        except requests.RequestException as exc:
            event.status = PaymentCalendarEvent.Status.FAILED
            event.error_message = str(exc)[:500]
            event.save(update_fields=["status", "error_message", "updated_at"])
            failed += 1
    return {"created": created, "failed": failed}


def ensure_access_token(connection):
    if connection.access_token and connection.token_expires_at and connection.token_expires_at > timezone.now() + timedelta(minutes=2):
        return connection.access_token
    if not connection.refresh_token:
        connection.is_active = False
        connection.save(update_fields=["is_active", "updated_at"])
        raise requests.RequestException("Conexão com Google Agenda expirada. Reconecte sua conta.")
    google_app = settings.SOCIALACCOUNT_PROVIDERS["google"]["APP"]
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": google_app["client_id"],
            "client_secret": google_app["secret"],
            "refresh_token": connection.refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    connection.access_token = payload["access_token"]
    connection.token_expires_at = timezone.now() + timedelta(seconds=payload.get("expires_in", 3600))
    connection.is_active = True
    connection.save(update_fields=["access_token_encrypted", "token_expires_at", "is_active", "updated_at"])
    return connection.access_token


def create_google_calendar_event(access_token, proposal):
    date_text = proposal["date"].isoformat()
    payload = {
        "summary": proposal["title"][:200],
        "description": proposal["description"][:1000],
        "start": {"date": date_text},
        "end": {"date": (proposal["date"] + timedelta(days=1)).isoformat()},
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 24 * 60},
                {"method": "popup", "minutes": 60},
            ],
        },
    }
    response = requests.post(
        EVENTS_URL.format(calendar_id="primary"),
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    return response.json()["id"]


def _event_description(payment):
    parts = [
        "Evento criado pelo Gastou Lembrou.",
        f"Valor: R$ {payment.amount:.2f}".replace(".", ","),
    ]
    if payment.payment_method_id:
        parts.append(f"Forma de pagamento: {payment.payment_method.name}.")
    if payment.has_installment_info:
        parts.append(f"Parcela: {payment.installment_number}/{payment.installment_total}.")
    return "\n".join(parts)
