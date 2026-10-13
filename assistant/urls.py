from django.urls import path

from .views import (
    CalendarAssistantView,
    CalendarCallbackView,
    CalendarConfirmView,
    CalendarConnectView,
    CalendarDisconnectView,
    SpikePanelView,
    spike_chat_view,
    spike_close_view,
    spike_payment_action_view,
)

app_name = "assistant"

urlpatterns = [
    path("spike/proposta/<uuid:pk>/", spike_payment_action_view, name="payment_action"),
    path("spike/", SpikePanelView.as_view(), name="spike_panel"),
    path("spike/mensagem/", spike_chat_view, name="spike_chat"),
    path("spike/fechar/", spike_close_view, name="spike_close"),
    path("google-agenda/", CalendarAssistantView.as_view(), name="calendar"),
    path("google-agenda/conectar/", CalendarConnectView.as_view(), name="calendar_connect"),
    path("google-agenda/callback/", CalendarCallbackView.as_view(), name="calendar_callback"),
    path("google-agenda/confirmar/", CalendarConfirmView.as_view(), name="calendar_confirm"),
    path("google-agenda/desconectar/", CalendarDisconnectView.as_view(), name="calendar_disconnect"),
]
