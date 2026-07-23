from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .categorization import gemini_category_match, local_category_match
from .forms import PaymentForm
from .models import Category, Payment
from .tasks import categorize_payment


User = get_user_model()


class PaymentCategorizationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Mercado")
        LegalAcceptance.objects.create(
            user=self.user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )

    def test_payment_form_allows_empty_category_for_automatic_selection(self):
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Uber para o trabalho",
                "category": "",
                "amount": "25.00",
                "payment_date": "2026-05-20",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertFalse(form.cleaned_data["category"])
        self.assertEqual(form.fields["category"].empty_label, "Selecionar automaticamente")

    def test_uncategorized_payment_renders_safely_while_task_is_pending(self):
        payment = Payment.objects.create(
            user=self.user,
            title="Pagamento sem categoria",
            amount=Decimal("25.00"),
        )
        self.client.force_login(self.user)

        list_response = self.client.get(reverse("payments:list"))
        detail_response = self.client.get(reverse("payments:detail", kwargs={"pk": payment.pk}))

        self.assertContains(list_response, "Categorização automática pendente")
        self.assertContains(detail_response, "Categorização automática pendente")

    @patch("payments.signals.queue_payment_categorization")
    def test_signal_queues_categorization_only_when_category_is_missing(self, queue_categorization):
        with self.captureOnCommitCallbacks(execute=True):
            uncategorized = Payment.objects.create(
                user=self.user,
                title="Uber para o trabalho",
                amount=Decimal("25.00"),
            )
        queue_categorization.assert_called_once_with(uncategorized.pk)

        queue_categorization.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            Payment.objects.create(
                user=self.user,
                category=self.category,
                title="Compra informada",
                amount=Decimal("30.00"),
            )
        queue_categorization.assert_not_called()

    def test_local_category_match_uses_title_semantics(self):
        food = Category.objects.create(name="Alimentação")
        transport = Category.objects.create(name="Transporte")

        selected = local_category_match("Uber para o trabalho", [food, transport])

        self.assertEqual(selected, transport)

    def test_local_category_match_understands_specific_category_name(self):
        transport = Category.objects.create(name="Transporte")

        selected = local_category_match("Compra no supermercado", [self.category, transport])

        self.assertEqual(selected, self.category)

    @override_settings(GEMINI_API_KEY="")
    def test_categorization_task_assigns_local_category(self):
        transport = Category.objects.create(name="Transporte")
        payment = Payment.objects.create(
            user=self.user,
            title="Uber para o trabalho",
            amount=Decimal("25.00"),
        )

        categorize_payment(payment.pk)

        payment.refresh_from_db()
        self.assertEqual(payment.category, transport)

    @patch("payments.tasks.choose_category_for_title")
    def test_categorization_task_does_not_change_user_selected_category(self, choose_category):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Compra",
            amount=Decimal("30.00"),
        )

        categorize_payment(payment.pk)

        payment.refresh_from_db()
        self.assertEqual(payment.category, self.category)
        choose_category.assert_not_called()

    @override_settings(
        GEMINI_API_KEY="test-key",
        GEMINI_MODEL="gemini-2.5-flash-lite",
        GEMINI_TIMEOUT_SECONDS=30,
    )
    @patch("payments.categorization.generate_content")
    def test_gemini_category_match_selects_only_existing_category(self, generate_content):
        transport = Category.objects.create(name="Transporte")
        generate_content.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": f'{{"category_id":"{transport.pk}"}}'}],
                    }
                }
            ]
        }

        selected = gemini_category_match("Corrida por aplicativo", [self.category, transport])

        self.assertEqual(selected, transport)
        generation_config = generate_content.call_args.args[0]["generationConfig"]
        self.assertEqual(generation_config["responseMimeType"], "application/json")
        schema = generation_config["responseSchema"]
        self.assertEqual(set(schema["properties"]["category_id"]["enum"]), {str(self.category.pk), str(transport.pk)})
