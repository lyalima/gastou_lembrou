import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pymupdf
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance
from assistant.actions import confirm_payment_action, propose_payment
from assistant.models import AssistantConversation, AssistantMessage
from dashboard.metrics import get_dashboard_metrics
from dashboard.reports import build_dashboard_report_pdf
from .forms import PaymentForm
from .models import Category, CreditCard, Payment, PaymentMethod


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class RequestedWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="workflow-new@example.com", password="test-password")
        self.other = get_user_model().objects.create_user(email="other-new@example.com", password="test-password")
        LegalAcceptance.objects.create(user=self.user, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION, source="email")
        self.category = Category.objects.create(user=self.user, name="Mercado")
        self.old_category = Category.objects.create(name="Outros")
        self.pix = PaymentMethod.objects.create(name="Pix")
        self.credit = PaymentMethod.objects.create(name="Cartão de crédito")
        self.card = CreditCard.objects.create(user=self.user, name="Principal", closing_day=19, due_day=25)
        self.conversation = AssistantConversation.objects.create(user=self.user)

    def payment(self, **kwargs):
        data = dict(user=self.user, title="Loja exemplo", amount=Decimal("100.00"), payment_date=date(2026, 9, 21), category=self.old_category)
        data.update(kwargs)
        return Payment.objects.create(**data)

    def test_manual_category_propagates_only_same_user_and_title(self):
        original = self.payment()
        same = self.payment(title=" LOJA EXEMPLO ")
        Payment.objects.filter(pk=same.pk).update(category=None)
        foreign = self.payment(user=self.other)
        different = self.payment(title="Loja exemplo filial")
        form = PaymentForm({"title": original.title, "amount": "100,00", "category": self.category.pk, "payment_date": "2026-09-21"}, instance=original, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        same.refresh_from_db()
        foreign.refresh_from_db()
        different.refresh_from_db()
        self.assertEqual(same.category_id, self.category.pk)
        self.assertEqual(foreign.category_id, self.old_category.pk)
        self.assertEqual(different.category_id, self.old_category.pk)

    def test_unrelated_edit_does_not_propagate_category(self):
        original = self.payment()
        same = self.payment(category=self.category)
        form = PaymentForm({"title": original.title, "amount": "101,00", "category": self.old_category.pk, "payment_date": "2026-09-21"}, instance=original, user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        same.refresh_from_db()
        self.assertEqual(same.category_id, self.category.pk)

    def test_dates_ordering_and_financial_month_are_independent(self):
        first = self.payment(title="Compra 1", payment_method=self.credit, credit_card=self.card)
        second = self.payment(title="Compra 2", payment_method=self.credit, credit_card=self.card, payment_date=date(2026, 9, 24))
        scheduled = self.payment(title="Previsto", payment_date=date(2026, 9, 1), scheduled_date=date(2026, 10, 2), payment_method=self.pix)
        regular = self.payment(title="Pix", payment_date=date(2026, 10, 1), payment_method=self.pix)
        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:list"), {"month": "10", "year": "2026"})
        self.assertEqual([p.pk for p in response.context["payments"]], [scheduled.pk, regular.pk])
        metrics = get_dashboard_metrics(self.user, date(2026, 10, 1))
        self.assertEqual(metrics["total"], Decimal("200"))
        self.assertEqual(metrics["month_labels"], ["01/10/2026", "02/10/2026"])
        self.assertEqual(sum(metrics["month_totals"]), 200)
        september = get_dashboard_metrics(self.user, date(2026, 9, 1))
        self.assertEqual(september["total"], 200)
        self.assertEqual(september["month_labels"], ["21/09/2026", "24/09/2026"])
        for filters, expected in (({"day": "2026-09-21"}, [first.pk]), ({"month": "9", "year": "2026"}, [second.pk, first.pk]), ({"day": "2026-10-25"}, [])):
            response = self.client.get(reverse("payments:list"), filters)
            self.assertEqual([p.pk for p in response.context["payments"]], expected)

    def test_draft_card_installments_and_double_confirmation(self):
        action = propose_payment(self.user, self.conversation, "create", {"title": "Mercado", "amount": "123.45", "payment_date": "2026-09-22", "payment_method": str(self.credit.pk), "credit_card": str(self.card.pk), "is_installment": True, "installment_total": 3, "installment_number": 1})
        self.assertFalse(Payment.objects.exists())
        review = {field["label"]: field["value"] for field in action.review_fields}
        self.assertEqual(review["Data da compra"], "22/09/2026")
        self.assertEqual(review["Vencimento da fatura"], "25/10/2026")
        confirm_payment_action(self.user, action.pk, "confirm")
        confirm_payment_action(self.user, action.pk, "confirm")
        self.assertEqual(Payment.objects.count(), 3)
        self.assertEqual(Payment.objects.aggregate(total=Sum("amount"))["total"], Decimal("370.35"))

    def test_creation_requires_date_and_rejects_foreign_card(self):
        foreign = CreditCard.objects.create(user=self.other, name="Privado", closing_day=10, due_day=20)
        for extra in ({}, {"payment_date": "2026-09-22", "credit_card": foreign.pk, "payment_method": self.credit.pk}):
            with self.assertRaises(ValidationError):
                propose_payment(self.user, self.conversation, "create", {"title": "Teste", "amount": "10", **extra})
        self.assertFalse(Payment.objects.exists())

    def creation_tool(self):
        from assistant.tools import build_spike_tools
        return next(tool for tool in build_spike_tools(self.user, allow_actions=True, conversation=self.conversation) if tool.name == "preparar_gasto")

    def test_creation_tool_resolves_names_and_preserves_confirmation(self):
        from assistant.models import AssistantPaymentAction
        category = Category.objects.create(user=self.user, name="Supermercado")
        result = json.loads(self.creation_tool().invoke({"title": "Supermercado Raimar", "amount": "22.99", "payment_date": "2026-10-02", "category": " supermercado ", "payment_method": "pix"}))
        self.assertIn("proposta", result)
        self.assertFalse(Payment.objects.exists())
        action = AssistantPaymentAction.objects.get(pk=result["proposta"], user=self.user)
        self.assertEqual(action.payload["category"], category.pk)
        self.assertEqual(action.payload["payment_method"], self.pix.pk)
        confirm_payment_action(self.user, action.pk, "confirm")
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, Decimal("22.99"))
        self.assertEqual(payment.category_id, category.pk)
        self.assertEqual(payment.payment_method_id, self.pix.pk)

    def test_creation_tool_resolves_accents_and_real_catalog_ids(self):
        for method in ("cartao de credito", str(self.credit.pk)):
            result = json.loads(self.creation_tool().invoke({"title": "Compra", "amount": "10", "payment_date": "2026-10-02", "category": str(self.category.pk), "payment_method": method, "credit_card": "principal"}))
            self.assertIn("proposta", result)
        self.assertFalse(Payment.objects.exists())

    def test_creation_resolves_card_prefix_and_uses_server_review_message(self):
        from assistant.models import AssistantPaymentAction
        self.card.name = "C6"
        self.card.save()
        for name in ("Cartão C6", "cartao de credito C6", "C6"):
            result = json.loads(self.creation_tool().invoke({"title": "Casa de Ração", "amount": "38", "payment_date": "2026-10-03", "payment_method": "Cartão de crédito", "credit_card": name}))
            self.assertIn("proposta", result)
            self.assertIn("Confirmar criação", result["mensagem_usuario"])
            action = AssistantPaymentAction.objects.get(pk=result["proposta"])
            self.assertEqual(action.payload["credit_card"], self.card.pk)
        self.assertFalse(Payment.objects.exists())

    def test_unknown_card_lists_only_own_cards_without_internal_commands(self):
        CreditCard.objects.create(user=self.other, name="Segredo", closing_day=10, due_day=20)
        result = json.loads(self.creation_tool().invoke({"title": "Compra", "amount": "38", "payment_date": "2026-10-03", "credit_card": "Inexistente"}))
        self.assertIn("Principal", result["mensagem_usuario"])
        self.assertNotIn("Segredo", result["mensagem_usuario"])
        self.assertNotIn("consultar_opcoes", result["mensagem_usuario"])

    def test_card_alias_does_not_guess_between_multiple_cards(self):
        CreditCard.objects.create(user=self.user, name="C6", closing_day=10, due_day=20)
        CreditCard.objects.create(user=self.user, name="Cartão C6", closing_day=15, due_day=25)
        result = json.loads(self.creation_tool().invoke({"title": "Compra", "amount": "38", "payment_date": "2026-10-03", "credit_card": "cartao de credito C6"}))
        self.assertIn("mais de uma", result["mensagem_usuario"])
        self.assertNotIn("proposta", result)

    def test_creation_tool_rejects_foreign_unknown_and_ambiguous_options(self):
        from assistant.models import AssistantPaymentAction
        foreign_category = Category.objects.create(user=self.other, name="Categoria privada")
        foreign_card = CreditCard.objects.create(user=self.other, name="Cartão privado", closing_day=10, due_day=20)
        Category.objects.create(name="Mercado")
        for field, value in (("category", foreign_category.name), ("category", str(foreign_category.pk)), ("credit_card", foreign_card.name), ("credit_card", str(foreign_card.pk)), ("category", "Mercado"), ("payment_method", "Inexistente")):
            with self.subTest(field=field, value=value):
                result = json.loads(self.creation_tool().invoke({"title": "Compra", "amount": "10", "payment_date": "2026-10-02", field: value}))
                self.assertIn("erro", result)
        self.assertFalse(AssistantPaymentAction.objects.exists())
        self.assertFalse(Payment.objects.exists())

    @patch("assistant.views.answer_spike", return_value={"answer": "Revisão pronta", "allowed": True})
    def test_chat_accepts_creation_request_without_old_checkbox(self, answer):
        self.client.force_login(self.user)
        response = self.client.post(reverse("assistant:spike_chat"), {"message": "Crie o gasto Mercado, 100 reais em 22/09"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(answer.call_args.kwargs["allow_actions"])

    @override_settings(GEMINI_API_KEY="test-only", SPIKE_MONTHLY_MESSAGE_LIMIT=0)
    @patch("assistant.graph.run_spike_graph", return_value="Revisão pronta")
    @patch("assistant.services.generate_content")
    def test_short_creation_followup_uses_existing_agent_without_extra_classifier(self, generate, graph):
        from assistant.services import answer_spike
        AssistantMessage.objects.create(user=self.user, conversation=self.conversation, role="user", content="Crie o gasto Supermercado XYZ de 100 reais")
        AssistantMessage.objects.create(user=self.user, conversation=self.conversation, role="assistant", content="Qual a data do gasto?")
        result = answer_spike(self.user, "22/09/2026", conversation=self.conversation, allow_actions=True)
        self.assertEqual(result["answer"], "Revisão pronta")
        generate.assert_not_called()
        self.assertTrue(graph.call_args.kwargs["allow_actions"])

    def test_report_keeps_details_and_bounds_across_pages(self):
        for index in range(25):
            self.payment(title=f"Compra {index} " + "Estabelecimento extenso " * 7, payment_method=self.credit, credit_card=self.card)
        self.payment(title="Previsto", scheduled_date=date(2026, 9, 22), payment_method=self.pix)
        self.payment(title="Pago em dinheiro", payment_date=date(2026, 9, 23), payment_method=self.pix)
        with pymupdf.open(stream=build_dashboard_report_pdf(self.user, date(2026, 9, 1)), filetype="pdf") as pdf:
            text = "\n".join(page.get_text() for page in pdf)
            self.assertGreater(len(pdf), 2)
            for label in ("Data da compra", "Vencimento da fatura", "Principal", "Data prevista", "Data de pagamento", "Pix", "25/10/2026", "21/09/2026"):
                self.assertIn(label, text)
            for index in range(25):
                self.assertIn(f"Compra {index} ", text)
            for page in pdf:
                for word in page.get_text("words"):
                    self.assertGreaterEqual(word[0], 40)
                    self.assertLessEqual(word[2], 553)
                    self.assertGreaterEqual(word[1], 15)
                    self.assertLessEqual(word[3], 836)
