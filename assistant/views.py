import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.decorators.http import require_POST

from kombu.exceptions import OperationalError

from .calendar import (
    GoogleCalendarConnectionError,
    build_event_proposals,
    build_google_calendar_auth_url,
    exchange_calendar_code,
    google_calendar_configured,
    validate_calendar_state,
)
from .models import GoogleCalendarConnection
from .services import (
    QUICK_ACTIONS,
    answer_spike,
    close_active_conversation,
    get_active_conversation,
    spike_greeting,
)
from .tasks import create_calendar_events_task


logger = logging.getLogger(__name__)


@login_required
@require_POST
def spike_chat_view(request):
    message = request.POST.get("message", "")
    result = answer_spike(request.user, message, conversation=get_active_conversation(request.user))
    return JsonResponse(result)


@login_required
@require_POST
def spike_close_view(request):
    close_active_conversation(request.user)
    return JsonResponse({"closed": True})


class SpikePanelView(LoginRequiredMixin, View):
    def get(self, request):
        conversation = get_active_conversation(request.user)
        return render(
            request,
            "assistant/partials/spike_panel.html",
            {
                "greeting": spike_greeting(request.user),
                "quick_actions": QUICK_ACTIONS,
                "conversation": conversation,
                "conversation_messages": conversation.messages.order_by("created_at"),
            },
        )


class CalendarAssistantView(LoginRequiredMixin, View):
    def get(self, request):
        connection = getattr(request.user, "google_calendar_connection", None)
        proposals = build_event_proposals(request.user) if connection and connection.is_active else []
        return render(
            request,
            "assistant/partials/calendar_modal.html",
            {
                "calendar_configured": google_calendar_configured(),
                "connection": connection,
                "proposals": proposals,
            },
        )


class CalendarConnectView(LoginRequiredMixin, View):
    def get(self, request):
        if not google_calendar_configured():
            messages.error(request, "Google Agenda ainda não está configurado no projeto.")
            return redirect("payments:list")
        return redirect(build_google_calendar_auth_url(request))


class CalendarCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        state = request.GET.get("state", "")
        code = request.GET.get("code", "")
        if not state or not code or not validate_calendar_state(request, state):
            messages.error(request, "Não foi possível validar a conexão com o Google Agenda.")
            return redirect("payments:list")
        try:
            exchange_calendar_code(request, code)
        except GoogleCalendarConnectionError as exc:
            logger.warning("Falha ao conectar Google Agenda para usuário %s: %s", request.user.pk, exc)
            if settings.DEBUG:
                messages.error(request, f"Não foi possível conectar o Google Agenda: {exc}")
            else:
                messages.error(request, "Não foi possível conectar o Google Agenda agora. Tente novamente.")
            return redirect("payments:list")
        except Exception:
            logger.exception("Erro inesperado ao conectar Google Agenda para usuário %s", request.user.pk)
            messages.error(request, "Não foi possível conectar o Google Agenda agora. Tente novamente.")
            return redirect("payments:list")
        messages.success(request, "Google Agenda conectado com sucesso.")
        return redirect("payments:list")


class CalendarConfirmView(LoginRequiredMixin, View):
    def post(self, request):
        selected_payment_ids = request.POST.getlist("payment_ids")
        if not selected_payment_ids:
            messages.error(request, "Selecione pelo menos um pagamento agendado para criar no Google Agenda.")
            if request.headers.get("HX-Request"):
                connection = getattr(request.user, "google_calendar_connection", None)
                return render(
                    request,
                    "assistant/partials/calendar_modal.html",
                    {
                        "calendar_configured": google_calendar_configured(),
                        "connection": connection,
                        "proposals": build_event_proposals(request.user) if connection and connection.is_active else [],
                    },
                )
            return redirect("payments:list")
        try:
            create_calendar_events_task.delay(request.user.pk, selected_payment_ids)
            messages.success(request, "Criação dos lembretes enviada para processamento.")
        except (OperationalError, OSError):
            result = create_calendar_events_task(request.user.pk, selected_payment_ids)
            messages.success(request, f"Lembretes processados: {result['created']} criado(s), {result['failed']} falha(s).")
        if request.headers.get("HX-Request"):
            response = render(request, "assistant/partials/calendar_success.html")
            response["HX-Redirect"] = reverse("payments:list")
            return response
        return redirect("payments:list")


class CalendarDisconnectView(LoginRequiredMixin, View):
    def post(self, request):
        GoogleCalendarConnection.objects.filter(user=request.user).update(is_active=False)
        messages.success(request, "Google Agenda desconectado.")
        if request.headers.get("HX-Request"):
            return render(
                request,
                "assistant/partials/calendar_modal.html",
                {
                    "calendar_configured": google_calendar_configured(),
                    "connection": None,
                    "proposals": [],
                },
            )
        return redirect("payments:list")
