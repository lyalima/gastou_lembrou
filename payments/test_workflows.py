from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.legal import TERMS_VERSION, PRIVACY_VERSION
from accounts.models import LegalAcceptance
from assistant.actions import propose_payment, confirm_payment_action
from assistant.models import AssistantConversation, AssistantPaymentAction
from assistant.tools import build_spike_tools
from .card_cycles import statement_due_date
from .forms import PaymentForm, CreditCardForm, CreditCardStatementImportForm
from .models import Category, CreditCard, Payment, PaymentMethod, PaymentRecurrence
from .recurrences import configure_recurrence, generate_occurrences


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(email="workflow@example.com", password="Test-pass-2026", email_verified=True)
        self.other = get_user_model().objects.create_user(email="other@example.com", password="Test-pass-2026")
        LegalAcceptance.objects.create(user=self.user, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION, source=LegalAcceptance.Source.EMAIL)
        self.category = Category.objects.create(user=self.user, name="Casa")
        self.method = PaymentMethod.objects.create(name="Cartão de crédito")
        self.card = CreditCard.objects.create(user=self.user, name="Meu cartão", closing_day=25, due_day=5)
        self.conversation = AssistantConversation.objects.create(user=self.user)

    def payment(self, **kwargs):
        data = dict(user=self.user, title="Internet", amount=Decimal("100.00"), category=self.category, payment_date=date(2026, 9, 21))
        data.update(kwargs)
        return Payment.objects.create(**data)

    def form_data(self, **kwargs):
        data = dict(title="Internet", amount="100,00", category=self.category.pk, payment_date="2026-09-21", kind="expense")
        data.update(kwargs)
        return data

    def proposal(self, **kwargs):
        return propose_payment(self.user, self.conversation, "create", {"title": "Internet", "amount": "100.00", "payment_date": "2026-09-21", **kwargs})

    def test_closing_boundary_next_month_and_year(self):
        self.assertEqual(statement_due_date(self.card, date(2026, 9, 24)), date(2026, 10, 5))
        self.assertEqual(statement_due_date(self.card, date(2026, 9, 25)), date(2026, 11, 5))
        self.assertEqual(statement_due_date(self.card, date(2026, 12, 25)), date(2027, 2, 5))

    def test_short_month_and_same_month_due(self):
        self.card.closing_day, self.card.due_day = 20, 31
        self.assertEqual(statement_due_date(self.card, date(2028, 2, 18)), date(2028, 2, 29))
        self.assertEqual(statement_due_date(self.card, date(2028, 2, 19)), date(2028, 3, 31))
        self.assertEqual(statement_due_date(self.card, date(2027, 2, 20)), date(2027, 3, 31))

    def test_card_day_validation(self):
        self.assertFalse(CreditCardForm({"name": "X", "closing_day": 0, "due_day": 32}).is_valid())

    def test_payment_uses_anticipated_sunday_closing(self):
        self.card.closing_day, self.card.due_day = 4, 10
        self.card.save()
        payment = self.payment(payment_method=self.method, credit_card=self.card, payment_date=date(2026, 10, 3))
        payment.refresh_from_db()
        self.assertEqual(payment.statement_due_date, date(2026, 11, 10))

    def test_new_models_do_not_block_account_deletion(self):
        from django.db.models.deletion import RestrictedError
        payment = self.payment(category=None, credit_card=self.card, payment_method=self.method)
        schedule = PaymentRecurrence.objects.create(source=payment, anchor_date=payment.payment_date, interval_months=1)
        self.proposal()
        with self.assertRaises(RestrictedError):
            self.card.delete()
        self.user.delete()
        self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
        self.assertFalse(PaymentRecurrence.objects.filter(pk=schedule.pk).exists())
        self.assertEqual(AssistantPaymentAction.objects.count(), 0)

    def test_card_ownership_and_method_validation(self):
        foreign = CreditCard.objects.create(user=self.other, name="Privado", closing_day=1, due_day=10)
        form = PaymentForm(self.form_data(credit_card=foreign.pk, payment_method=self.method.pk), user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("credit_card", form.errors)
        self.assertFalse(PaymentForm(self.form_data(credit_card=self.card.pk), user=self.user).is_valid())
        with self.assertRaises(ValidationError):
            self.payment(credit_card=foreign, payment_method=self.method)

    def test_card_form_and_import_options_are_scoped(self):
        self.assertEqual(list(CreditCardStatementImportForm(user=self.other).fields["credit_card"].queryset), [])
        form = PaymentForm(self.form_data(credit_card=self.card.pk, payment_method=self.method.pk), user=self.user)
        self.assertTrue(form.is_valid(), form.errors)
        form.instance.user = self.user
        payment = form.save()
        self.assertEqual(payment.statement_due_date, date(2026, 10, 5))
        self.assertTrue(PaymentForm(instance=payment, user=self.user).show_installment_field)

    def test_dashboard_cards_do_not_double_totals(self):
        self.payment(payment_method=self.method, credit_card=self.card)
        self.client.force_login(self.user)
        september = self.client.get(reverse("dashboard:home"), {"month": "2026-09"})
        october = self.client.get(reverse("dashboard:home"), {"month": "2026-10"})
        self.assertEqual(september.context["total"], Decimal("100"))
        self.assertEqual(september.context["card_summaries"][0]["current"], 0)
        self.assertEqual(september.context["card_summaries"][0]["next"], Decimal("100"))
        self.assertEqual(october.context["total"], 0)
        self.assertEqual(october.context["card_summaries"][0]["current"], Decimal("100"))

    def test_invoice_page_filters_card_and_month_and_keeps_data_private(self):
        purchase = self.payment(title="Compra certa", payment_method=self.method, credit_card=self.card)
        other_card = CreditCard.objects.create(user=self.other, name="Cartão alheio", closing_day=25, due_day=5)
        Payment.objects.create(
            user=self.other, title="Compra privada", amount=Decimal("999.00"),
            payment_method=self.method, credit_card=other_card, payment_date=date(2026, 9, 21),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:invoices"), {"card": self.card.pk, "month": "2026-10"})
        self.assertContains(response, purchase.title)
        self.assertNotContains(response, "Compra privada")
        self.assertEqual(response.context["invoice_total"], Decimal("100.00"))
        self.assertContains(response, 'aria-current="page"')

        foreign = self.client.get(reverse("payments:invoices"), {"card": other_card.pk, "month": "2026-10"})
        self.assertNotContains(foreign, "Compra privada")
        self.assertFalse(foreign.context["has_selection"])

        wrong_month = self.client.get(reverse("payments:invoices"), {"card": self.card.pk, "month": "2026-09"})
        self.assertEqual(wrong_month.context["invoice_total"], 0)

    def test_dashboard_invoice_links_open_selected_card_and_month(self):
        self.payment(payment_method=self.method, credit_card=self.card)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:home"), {"month": "2026-09"})
        self.assertContains(response, f"{reverse('payments:invoices')}?card={self.card.pk}&amp;month=2026-10")

    def test_bill_keeps_card_without_payment_method_and_is_not_an_expense(self):
        bill = self.payment(
            title="Fatura Meu cartão", category=None, credit_card=self.card,
            payment_method=None, kind=Payment.Kind.CREDIT_CARD_BILL,
        )
        self.assertEqual(bill.credit_card, self.card)
        self.assertIsNone(bill.payment_method)
        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:invoices"), {"card": self.card.pk, "month": "2026-09"})
        self.assertEqual(response.context["invoice_total"], 0)

    def test_card_purchase_and_pix_share_purchase_month_but_invoice_keeps_due_month(self):
        from dashboard.metrics import get_available_report_months, get_dashboard_metrics

        self.card.closing_day, self.card.due_day = 19, 25
        self.card.save()
        card_payment = self.payment(title="Compra no cartão", payment_method=self.method, credit_card=self.card)
        pix = PaymentMethod.objects.create(name="Pix")
        self.payment(title="Compra no Pix", payment_method=pix)

        self.assertEqual(card_payment.statement_due_date, date(2026, 10, 25))
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 9, 1))["total"], Decimal("200"))
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 10, 1))["total"], Decimal("0"))
        self.assertEqual(
            [item["value"] for item in get_available_report_months(self.user)[:2]],
            ["2026-09"],
        )
        self.client.force_login(self.user)
        cards_page = self.client.get(reverse("payments:cards"))
        self.assertContains(cards_page, "Compra no cartão")
        self.assertContains(cards_page, "Fatura 10/2026")

    def test_linked_installments_follow_consecutive_card_invoices(self):
        from .installments import create_installment_siblings

        self.card.closing_day, self.card.due_day = 19, 25
        self.card.save()
        payment = self.payment(
            payment_method=self.method, credit_card=self.card, is_installment=True,
            installment_number=1, installment_total=3,
        )
        create_installment_siblings(payment)
        due_dates = list(
            Payment.objects.filter(installment_group=payment.installment_group)
            .order_by("installment_number").values_list("statement_due_date", flat=True)
        )
        self.assertEqual(due_dates, [date(2026, 10, 25), date(2026, 11, 25), date(2026, 12, 25)])

    def test_middle_installment_keeps_previous_and_next_invoice_months(self):
        from .installments import create_installment_siblings

        self.card.closing_day, self.card.due_day = 19, 25
        self.card.save()
        payment = self.payment(
            payment_method=self.method, credit_card=self.card, is_installment=True,
            installment_number=3, installment_total=5,
        )
        create_installment_siblings(payment)
        due_dates = list(
            Payment.objects.filter(installment_group=payment.installment_group)
            .order_by("installment_number").values_list("statement_due_date", flat=True)
        )
        self.assertEqual(due_dates, [
            date(2026, 8, 25), date(2026, 9, 25), date(2026, 10, 25),
            date(2026, 11, 25), date(2026, 12, 25),
        ])

    def test_future_card_installment_uses_invoice_due_date(self):
        from .installments import create_installment_siblings

        self.card.closing_day, self.card.due_day = 19, 25
        self.card.save()
        payment = self.payment(
            payment_method=self.method, credit_card=self.card, is_installment=True,
            installment_number=1, installment_total=3,
        )
        create_installment_siblings(payment)
        self.client.force_login(self.user)
        with patch("payments.views.timezone.localdate", return_value=date(2026, 9, 22)):
            response = self.client.get(reverse("payments:list"))
        self.assertEqual(list(response.context["payments"]), [])
        self.assertEqual(
            [item.installment_number for item in response.context["future_installments"]],
            [1, 2, 3],
        )

    def test_last_card_installment_stays_pending_until_after_invoice_due_date(self):
        self.card.closing_day, self.card.due_day = 19, 25
        self.card.save()
        payment = self.payment(
            payment_method=self.method, credit_card=self.card, is_installment=True,
            installment_number=3, installment_total=3,
        )
        with patch("payments.models.timezone.localdate", return_value=date(2026, 10, 25)):
            self.assertFalse(payment.is_installment_finished)
        with patch("payments.models.timezone.localdate", return_value=date(2026, 10, 26)):
            self.assertTrue(payment.is_installment_finished)

    def test_card_edit_only_own(self):
        self.client.force_login(self.other)
        # Bypass legal gate only for this ownership check.
        LegalAcceptance.objects.create(user=self.other, terms_version=TERMS_VERSION, privacy_version=PRIVACY_VERSION, source=LegalAcceptance.Source.EMAIL)
        self.assertEqual(self.client.get(reverse("payments:card_update", args=[self.card.pk])).status_code, 404)

    def test_history_exact_normalized_and_user_scope(self):
        self.payment(title="Água - Casa")
        payment = self.payment(title="agua casa", category=None)
        self.assertEqual(payment.category_id, self.category.pk)
        other = self.payment(user=self.other, title="agua casa", category=None)
        self.assertIsNone(other.category_id)

    def test_explicit_category_is_never_replaced(self):
        self.payment()
        new_category = Category.objects.create(name="Outros")
        self.assertEqual(self.payment(category=new_category).category_id, new_category.pk)

    def test_statement_preview_prefers_users_history(self):
        from .credit_card_statement_import import CardStatementEntry, process_credit_card_statement
        from .models import CreditCardStatement
        self.payment(title="Supermercado Teste")
        Category.objects.create(name="Alimentação")
        statement = CreditCardStatement.objects.create(user=self.user, file="test-only.pdf")
        entry = CardStatementEntry("Supermercado Teste", Decimal("10.00"), date(2026, 9, 21), {})
        with patch("payments.credit_card_statement_import.extract_pdf_text", return_value="texto " * 100), patch("payments.credit_card_statement_import.parse_credit_card_entries", return_value=([entry], "text")):
            items = process_credit_card_statement(statement)
        self.assertEqual(items[0].category_id, self.category.pk)

    def test_recurring_requires_date_frequency_and_no_installments(self):
        for changes in [{"payment_date": ""}, {"recurrence_frequency": ""}, {"is_installment": True, "payment_method": self.method.pk, "installment_total": "3", "installment_number": "1"}]:
            data = self.form_data(is_recurring=True, recurrence_frequency="1")
            data.update(changes)
            self.assertFalse(PaymentForm(data, user=self.user).is_valid())

    @patch("payments.recurrences.timezone.localdate", return_value=date(2028, 1, 31))
    def test_recurrence_31st_idempotency_and_progress(self, today):
        payment = self.payment(payment_date=date(2028, 1, 31))
        configure_recurrence(payment, {"is_recurring": True, "recurrence_frequency": 1})
        schedule = payment.recurring_schedule
        self.assertEqual(schedule.occurrences.get().scheduled_date, date(2028, 2, 29))
        self.assertEqual(generate_occurrences(schedule.pk), 0)
        today.return_value = date(2028, 2, 29)
        self.assertEqual(generate_occurrences(schedule.pk), 1)
        self.assertTrue(schedule.occurrences.filter(scheduled_date=date(2028, 3, 31)).exists())
        configure_recurrence(payment, {"is_recurring": False})
        today.return_value = date(2030, 1, 1)
        self.assertEqual(generate_occurrences(schedule.pk), 0)
        self.assertEqual(schedule.occurrences.count(), 2)

    @patch("payments.recurrences.timezone.localdate", return_value=date(2026, 1, 15))
    def test_all_frequencies(self, today):
        for frequency, expected in [(1, date(2026, 2, 15)), (3, date(2026, 4, 15)), (6, date(2026, 7, 15)), (12, date(2027, 1, 15))]:
            p = self.payment(payment_date=date(2026, 1, 15))
            configure_recurrence(p, {"is_recurring": True, "recurrence_frequency": frequency})
            self.assertEqual(p.recurring_schedule.occurrences.get().scheduled_date, expected)

    def test_no_payment_saved_before_confirmation_and_replay(self):
        action = self.proposal()
        self.assertEqual(Payment.objects.count(), 0)
        confirm_payment_action(self.user, action.pk, "confirm")
        confirm_payment_action(self.user, action.pk, "confirm")
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(Payment.objects.get().amount, Decimal("100.00"))

    def test_other_user_cannot_confirm_or_edit(self):
        action = self.proposal()
        with self.assertRaises(AssistantPaymentAction.DoesNotExist):
            confirm_payment_action(self.other, action.pk, "confirm")
        p = self.payment(user=self.other, category=None)
        with self.assertRaises(ValidationError):
            propose_payment(self.user, self.conversation, "update", {"amount": "200.00"}, str(p.pk))

    def test_expiry_cancellation_and_closed_conversation(self):
        action = self.proposal()
        action.expires_at = timezone.now() - timedelta(seconds=1)
        action.save()
        with self.assertRaises(ValidationError):
            confirm_payment_action(self.user, action.pk, "confirm")
        action = self.proposal()
        confirm_payment_action(self.user, action.pk, "cancel")
        confirm_payment_action(self.user, action.pk, "confirm")
        self.assertEqual(Payment.objects.count(), 0)
        action = self.proposal()
        self.conversation.close()
        with self.assertRaises(ValidationError):
            confirm_payment_action(self.user, action.pk, "confirm")

    def test_update_preserves_unspecified_fields_and_stale_rejected(self):
        p = self.payment(description="Preservar")
        action = propose_payment(self.user, self.conversation, "update", {"amount": "42.50"}, str(p.pk))
        confirm_payment_action(self.user, action.pk, "confirm")
        p.refresh_from_db()
        self.assertEqual(p.amount, Decimal("42.50"))
        self.assertEqual(p.description, "Preservar")
        action = propose_payment(self.user, self.conversation, "update", {"title": "Nova"}, str(p.pk))
        p.description = "Mudou"
        p.save()
        with self.assertRaises(ValidationError):
            confirm_payment_action(self.user, action.pk, "confirm")

    def test_unrequested_fields_and_nan_rejected(self):
        for fields in [{"user": self.other.pk}, {"amount": "NaN"}, {"amount": "Infinity"}, {"amount": "0.001"}]:
            with self.assertRaises(ValidationError):
                self.proposal(**fields)

    def test_write_tools_require_opt_in(self):
        self.assertNotIn("preparar_gasto", [tool.name for tool in build_spike_tools(self.user)])
        self.assertIn("preparar_gasto", [tool.name for tool in build_spike_tools(self.user, allow_actions=True, conversation=self.conversation)])

    def test_proposal_tool_schema_binds_and_only_creates_draft(self):
        from langchain_google_genai import ChatGoogleGenerativeAI
        tools = build_spike_tools(self.user, allow_actions=True, conversation=self.conversation)
        model = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", google_api_key="test-only-no-network")
        self.assertIsNotNone(model.bind_tools(tools))
        tool = next(tool for tool in tools if tool.name == "preparar_gasto")
        result = tool.invoke({"title": "Internet", "amount": "100.00", "payment_date": "2026-09-21"})
        self.assertIn("aguardando", result)
        self.assertEqual(AssistantPaymentAction.objects.count(), 1)
        self.assertEqual(Payment.objects.count(), 0)

    def test_proposal_normalizes_localized_dates_and_escapes_html(self):
        from django.template.loader import render_to_string
        action = self.proposal(title="<script>alert(1)</script>", payment_date="21/09/2026")
        self.assertEqual(action.payload["payment_date"], "2026-09-21")
        html = render_to_string("assistant/partials/payment_actions.html", {"payment_actions": [action]})
        self.assertNotIn("<script>", html)
        self.assertIn("21/09/2026", html)

    @patch("payments.recurrences.timezone.localdate", return_value=date(2026, 9, 21))
    def test_recurring_http_create_and_disable(self, today):
        self.client.force_login(self.user)
        response = self.client.post(reverse("payments:create"), self.form_data(is_recurring="on", recurrence_frequency="3"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        source = Payment.objects.get(recurrence__isnull=True)
        schedule = source.recurring_schedule
        self.assertEqual(schedule.occurrences.get().scheduled_date, date(2026, 12, 21))
        response = self.client.post(reverse("payments:update", args=[source.pk]), self.form_data())
        self.assertEqual(response.status_code, 302)
        schedule.refresh_from_db()
        self.assertFalse(schedule.active)
        self.assertEqual(Payment.objects.count(), 2)

    def test_scheduled_proposal_confirmation_queues_after_commit(self):
        action = self.proposal(scheduled_date="2026-10-01")
        with patch("assistant.actions.queue_payment_confirmation") as queue:
            with self.captureOnCommitCallbacks(execute=True), patch("payments.signals.queue_payment_categorization"), patch("dashboard.tasks.queue_spending_goal_alert_check"):
                confirm_payment_action(self.user, action.pk, "confirm")
            queue.assert_called_once()

    def test_close_and_confirmed_action_history(self):
        action = self.proposal()
        confirm_payment_action(self.user, action.pk, "confirm")
        self.assertEqual(self.conversation.messages.filter(intent="payment_action").count(), 1)
        confirm_payment_action(self.user, action.pk, "confirm")
        self.assertEqual(self.conversation.messages.filter(intent="payment_action").count(), 1)

    def test_confirmation_endpoint_post_only_and_csrf(self):
        from django.test import Client
        action = self.proposal()
        self.client.force_login(self.user)
        url = reverse("assistant:payment_action", args=[action.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(url, {"decision": "confirm"}).status_code, 403)
        self.assertEqual(Payment.objects.count(), 0)

    def test_session_deadline_24h_and_no_store(self):
        self.client.force_login(self.user)
        expiry = self.client.session["auth_expires_at"]
        self.assertAlmostEqual(expiry - timezone.now().timestamp(), 86400, delta=5)
        response = self.client.get(reverse("payments:list"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(self.client.session["auth_expires_at"], expiry)

    def test_expired_session_htmx_full_redirect(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["auth_expires_at"] = timezone.now().timestamp() - 1
        session.save()
        response = self.client.get(reverse("payments:create"), HTTP_HX_REQUEST="true")
        self.assertEqual(response["HX-Redirect"], reverse("account_login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_expired_cookie_htmx_redirect(self):
        response = self.client.get(reverse("payments:create"), HTTP_HX_REQUEST="true")
        self.assertTrue(response["HX-Redirect"].startswith(reverse("account_login")))
