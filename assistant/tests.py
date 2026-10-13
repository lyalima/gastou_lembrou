from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance
from payments.models import Category, Payment, PaymentMethod

from .calendar import build_event_proposals, exchange_calendar_code
from .graph import run_spike_graph
from .intents import OUT_OF_SCOPE_MESSAGE, classify_message
from .models import (
    AssistantConversation,
    AssistantKnowledgeDocument,
    AssistantMessage,
    GoogleCalendarConnection,
)
from .rag import retrieve_knowledge
from .tools import _filtered_payments


User = get_user_model()


class SpikeAssistantTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.other_user = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Contas")
        self.factory = RequestFactory()
        LegalAcceptance.objects.create(
            user=self.user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )
        LegalAcceptance.objects.create(
            user=self.other_user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )

    @override_settings(GEMINI_API_KEY="")
    def test_spike_blocks_out_of_scope_message_without_internal_error(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": "Quem é o atual presidente do Brasil?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["answer"], OUT_OF_SCOPE_MESSAGE)

    @override_settings(GEMINI_API_KEY="")
    def test_spike_scheduled_answer_is_scoped_to_logged_user(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta de luz",
            amount=Decimal("120.00"),
            scheduled_date=date(2026, 9, 8),
        )
        Payment.objects.create(
            user=self.other_user,
            category=self.category,
            title="Conta privada da Bia",
            amount=Decimal("999.00"),
            scheduled_date=date(2026, 9, 9),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": "Liste os gastos agendados"})

        self.assertContains(response, "Conta de luz")
        self.assertNotContains(response, "Conta privada da Bia")

    @override_settings(GEMINI_API_KEY="")
    def test_spike_future_installments_quick_action_lists_future_installments(self):
        card = PaymentMethod.objects.create(name="Cartão de crédito")
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=card,
            title="Notebook",
            amount=Decimal("200.00"),
            payment_date=timezone.localdate() + timedelta(days=1),
            is_installment=True,
            installment_number=2,
            installment_total=3,
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": "Mostre minhas compras parceladas futuras"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "future_installments")
        self.assertIn("Notebook", payload["answer"])
        self.assertIn("2/3", payload["answer"])

    @override_settings(GEMINI_API_KEY="")
    def test_spike_answers_most_used_payment_method_for_current_month(self):
        current = timezone.localdate().replace(day=1)
        pix = PaymentMethod.objects.create(name="Pix")
        card = PaymentMethod.objects.create(name="Cartão de crédito")
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=pix,
            title="Mercado",
            amount=Decimal("80.00"),
            payment_date=current.replace(day=5),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=pix,
            title="Farmácia",
            amount=Decimal("40.00"),
            payment_date=current.replace(day=6),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=card,
            title="Curso",
            amount=Decimal("300.00"),
            payment_date=current.replace(day=7),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": "qual foi a forma de pagamento mais usada neste mês?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "payment_methods")
        self.assertIn("Pix", payload["answer"])
        self.assertIn("2 pagamento", payload["answer"])

    @override_settings(GEMINI_API_KEY="")
    @patch("assistant.graph.run_spike_graph")
    def test_spike_answers_most_used_category_for_previous_month_without_api_key(self, run_graph):
        current = timezone.localdate().replace(day=1)
        previous = (current - timedelta(days=1)).replace(day=1)
        food = Category.objects.create(name="Alimentação")
        transport = Category.objects.create(name="Transporte")
        Payment.objects.create(
            user=self.user,
            category=food,
            title="Mercado",
            amount=Decimal("80.00"),
            payment_date=previous.replace(day=5),
        )
        Payment.objects.create(
            user=self.user,
            category=food,
            title="Restaurante",
            amount=Decimal("40.00"),
            payment_date=previous.replace(day=6),
        )
        Payment.objects.create(
            user=self.user,
            category=transport,
            title="Passagem",
            amount=Decimal("500.00"),
            payment_date=previous.replace(day=7),
        )
        Payment.objects.create(
            user=self.other_user,
            category=transport,
            title="Pagamento privado",
            amount=Decimal("999.00"),
            payment_date=previous.replace(day=8),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:spike_chat"),
            {"message": "qual categoria de gastos foi mais utilizada no mês anterior?"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "category_ranking")
        self.assertIn("Alimentação", payload["answer"])
        self.assertIn(previous.strftime("%m/%Y"), payload["answer"])
        self.assertIn("2 pagamento", payload["answer"])
        run_graph.assert_not_called()

    def test_compound_financial_question_is_not_reduced_to_generic_summary(self):
        intent = classify_message("compare meus gastos com cartão entre os últimos três meses")

        self.assertEqual(intent, "financial_question")

    @override_settings(GEMINI_API_KEY="", SPIKE_RAG_EMBEDDINGS_ENABLED=False)
    def test_spike_answers_custom_category_feature_from_local_knowledge(self):
        call_command("sync_spike_knowledge")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:spike_chat"),
            {"message": "eu posso cadastrar no sistema uma categoria personalizada para meus gastos?"},
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "system_help")
        self.assertIn("pode cadastrar categorias personalizadas", payload["answer"])
        self.assertNotIn("Não encontrei a categoria", payload["answer"])

    @override_settings(GEMINI_API_KEY="", SPIKE_RAG_EMBEDDINGS_ENABLED=False)
    def test_spike_lists_personal_data_from_privacy_knowledge_without_ai(self):
        call_command("sync_spike_knowledge")
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:spike_chat"),
            {"message": "liste quais dados meus são tratados pelo sistema após o cadastro e aceite dos termos"},
        )

        payload = response.json()
        self.assertEqual(payload["intent"], "system_help")
        self.assertIn("Conta e autenticação", payload["answer"])
        self.assertIn("Pagamentos e gastos", payload["answer"])
        self.assertIn("Spike", payload["answer"])

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("assistant.graph._invoke_agent", return_value="")
    def test_spike_graph_rejects_empty_model_answer(self, invoke_agent):
        with self.assertRaisesRegex(RuntimeError, "resposta vazia"):
            run_spike_graph(self.user, "Quanto gastei?", [])

    @override_settings(GEMINI_API_KEY="test-key")
    @patch("assistant.graph.run_spike_graph", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED"))
    def test_spike_reports_temporary_ai_limit_instead_of_incorrect_generic_answer(self, run_graph):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("assistant:spike_chat"),
            {"message": "compare meus gastos com cartão entre os últimos três meses"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("temporariamente indisponível", response.json()["answer"])
        run_graph.assert_called_once()

    @override_settings(GEMINI_API_KEY="")
    def test_spike_lists_current_month_expenses_by_category(self):
        current = timezone.localdate().replace(day=1)
        fast_food = Category.objects.create(name="Fast Food")
        Payment.objects.create(
            user=self.user,
            category=fast_food,
            title="Hamburgueria",
            amount=Decimal("35.90"),
            payment_date=current.replace(day=12),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta de internet",
            amount=Decimal("99.90"),
            payment_date=current.replace(day=13),
        )
        Payment.objects.create(
            user=self.other_user,
            category=fast_food,
            title="Fast food privado da Bia",
            amount=Decimal("999.00"),
            payment_date=current.replace(day=14),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": 'liste meus gastos deste mês da categoria "Fast Food"'})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["intent"], "category_expenses")
        self.assertIn("Hamburgueria", payload["answer"])
        self.assertIn("R$ 35,90", payload["answer"])
        self.assertNotIn("Conta de internet", payload["answer"])
        self.assertNotIn("Fast food privado da Bia", payload["answer"])

    def test_calendar_proposals_are_scoped_to_logged_user_and_only_scheduled(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento da Ana",
            amount=Decimal("80.00"),
            scheduled_date=tomorrow,
        )
        Payment.objects.create(
            user=self.other_user,
            category=self.category,
            title="Pagamento da Bia",
            amount=Decimal("999.00"),
            scheduled_date=tomorrow,
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Parcela futura",
            amount=Decimal("50.00"),
            payment_date=tomorrow + timedelta(days=1),
            is_installment=True,
            installment_number=2,
            installment_total=3,
        )

        proposals = build_event_proposals(self.user)

        self.assertEqual([proposal["payment"].title for proposal in proposals], ["Pagamento da Ana"])

    def test_calendar_proposals_ignore_past_schedules(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento vencido",
            amount=Decimal("80.00"),
            scheduled_date=timezone.localdate() - timedelta(days=1),
        )

        self.assertEqual(build_event_proposals(self.user), [])

    def test_calendar_modal_renders_payment_selection_and_disconnect_button(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        connection = GoogleCalendarConnection.objects.create(user=self.user, google_email=self.user.email)
        connection.access_token = "calendar-token"
        connection.is_active = True
        connection.save()
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento selecionável",
            amount=Decimal("80.00"),
            scheduled_date=tomorrow,
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("assistant:calendar"))

        self.assertContains(response, 'name="payment_ids"')
        self.assertContains(response, "Pagamento selecionável")
        self.assertContains(response, "Desconectar")

    def test_calendar_disconnect_deactivates_connection(self):
        connection = GoogleCalendarConnection.objects.create(user=self.user, google_email=self.user.email, is_active=True)
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:calendar_disconnect"))

        connection.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertFalse(connection.is_active)

    @patch("assistant.views.create_calendar_events_task.delay")
    def test_calendar_confirm_uses_only_selected_payment_ids(self, delay):
        tomorrow = timezone.localdate() + timedelta(days=1)
        first = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento escolhido",
            amount=Decimal("80.00"),
            scheduled_date=tomorrow,
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento não escolhido",
            amount=Decimal("90.00"),
            scheduled_date=tomorrow + timedelta(days=1),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:calendar_confirm"), {"payment_ids": [str(first.pk)]})

        self.assertEqual(response.status_code, 302)
        delay.assert_called_once_with(self.user.pk, [str(first.pk)])

    def test_calendar_proposals_can_be_filtered_by_selected_payment_ids(self):
        tomorrow = timezone.localdate() + timedelta(days=1)
        first = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento escolhido",
            amount=Decimal("80.00"),
            scheduled_date=tomorrow,
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento não escolhido",
            amount=Decimal("90.00"),
            scheduled_date=tomorrow + timedelta(days=1),
        )

        proposals = build_event_proposals(self.user, payment_ids=[str(first.pk)])

        self.assertEqual([proposal["payment"].title for proposal in proposals], ["Pagamento escolhido"])

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "EMAIL_AUTHENTICATION": True,
                "APP": {"client_id": "google-client-id", "secret": "google-secret", "key": ""},
            }
        }
    )
    def test_google_calendar_connect_accepts_uuid_user_id_in_state(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("assistant:calendar_connect"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("accounts.google.com", response["Location"])
        self.assertIn("state=", response["Location"])

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "EMAIL_AUTHENTICATION": True,
                "APP": {"client_id": "google-client-id", "secret": "google-secret", "key": ""},
            }
        }
    )
    @patch("assistant.calendar.requests.post")
    def test_calendar_code_exchange_does_not_require_userinfo_scope(self, post):
        post.return_value = Mock(
            ok=True,
            json=lambda: {
                "access_token": "calendar-token",
                "refresh_token": "refresh-token",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events",
            },
        )
        request = self.factory.get(reverse("assistant:calendar_callback"))
        request.user = self.user

        connection = exchange_calendar_code(request, "google-code")

        self.assertEqual(connection.google_email, self.user.email)
        self.assertEqual(connection.access_token, "calendar-token")
        post.assert_called_once()

    @override_settings(GEMINI_API_KEY="", SPIKE_MONTHLY_MESSAGE_LIMIT=1)
    def test_spike_respects_monthly_message_limit(self):
        AssistantMessage.objects.create(
            user=self.user,
            role=AssistantMessage.Role.USER,
            content="Mensagem anterior",
            intent="summary",
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("assistant:spike_chat"), {"message": "Resuma meus gastos"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["allowed"])
        self.assertEqual(payload["intent"], "limit_reached")

    @override_settings(GEMINI_API_KEY="")
    def test_spike_panel_restores_active_conversation_history(self):
        self.client.force_login(self.user)
        self.client.post(reverse("assistant:spike_chat"), {"message": "Liste os gastos agendados"})

        response = self.client.get(reverse("assistant:spike_panel"))

        self.assertContains(response, "Liste os gastos agendados")
        self.assertContains(response, "Você não tem pagamentos agendados")
        self.assertContains(response, "data-spike-minimize")

    @override_settings(GEMINI_API_KEY="")
    def test_closing_spike_starts_a_new_empty_conversation(self):
        self.client.force_login(self.user)
        self.client.post(reverse("assistant:spike_chat"), {"message": "Resuma meus gastos"})
        previous = AssistantConversation.objects.get(user=self.user, status=AssistantConversation.Status.ACTIVE)

        response = self.client.post(reverse("assistant:spike_close"))

        self.assertEqual(response.status_code, 200)
        previous.refresh_from_db()
        self.assertEqual(previous.status, AssistantConversation.Status.CLOSED)
        panel = self.client.get(reverse("assistant:spike_panel"))
        current = AssistantConversation.objects.get(user=self.user, status=AssistantConversation.Status.ACTIVE)
        self.assertNotEqual(current.pk, previous.pk)
        self.assertFalse(current.messages.exists())
        self.assertContains(panel, "Eu sou o Spike")

    def test_financial_tool_queryset_never_returns_another_users_payments(self):
        own = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Pagamento da Ana",
            amount=Decimal("50.00"),
            payment_date=date(2026, 9, 1),
        )
        Payment.objects.create(
            user=self.other_user,
            category=self.category,
            title="Pagamento secreto da Bia",
            amount=Decimal("999.00"),
            payment_date=date(2026, 9, 1),
        )

        result = _filtered_payments(self.user)

        self.assertEqual(list(result), [own])

    @override_settings(SPIKE_RAG_EMBEDDINGS_ENABLED=False)
    def test_knowledge_sync_and_retrieval_find_system_documentation(self):
        call_command("sync_spike_knowledge")

        results = retrieve_knowledge("Como importar uma fatura de cartão em PDF?")

        self.assertTrue(AssistantKnowledgeDocument.objects.filter(is_active=True).exists())
        self.assertTrue(results)
        self.assertIn("fatura", results[0]["content"].lower())

    @override_settings(GEMINI_API_KEY="test-key", SPIKE_RAG_ENABLED=False)
    @patch("assistant.graph._invoke_agent", return_value="Resposta produzida pelo grafo")
    def test_langgraph_orchestrates_spike_response(self, invoke_agent):
        answer = run_spike_graph(self.user, "Quanto gastei?", [])

        self.assertEqual(answer, "Resposta produzida pelo grafo")
        invoke_agent.assert_called_once()
