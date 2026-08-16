from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .models import Category, Payment, PaymentMethod


User = get_user_model()


class PaymentInstallmentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Compras")
        self.card_method = PaymentMethod.objects.create(name="Cartão de crédito")
        LegalAcceptance.objects.create(
            user=self.user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )

    def test_first_credit_card_installment_creates_following_installments(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:create"),
            {
                "title": "Notebook",
                "category": self.category.pk,
                "amount": "300,00",
                "payment_method": self.card_method.pk,
                "is_installment": "on",
                "installment_total": "3",
                "installment_number": "1",
                "payment_date": "2026-08-05",
            },
        )

        self.assertEqual(response.status_code, 302)
        payments = Payment.objects.filter(title="Notebook").order_by("installment_number")
        self.assertEqual(payments.count(), 3)
        self.assertEqual([payment.installment_number for payment in payments], [1, 2, 3])
        self.assertEqual([payment.installment_total for payment in payments], [3, 3, 3])
        self.assertEqual([payment.amount for payment in payments], [Decimal("300.00")] * 3)
        self.assertEqual(
            [payment.payment_date for payment in payments],
            [date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)],
        )
        self.assertEqual(len({payment.installment_group for payment in payments}), 1)

    def test_middle_credit_card_installment_creates_previous_and_following_installments(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:create"),
            {
                "title": "Curso",
                "category": self.category.pk,
                "amount": "120,00",
                "payment_method": self.card_method.pk,
                "is_installment": "on",
                "installment_total": "5",
                "installment_number": "3",
                "payment_date": "2026-08-05",
            },
        )

        self.assertEqual(response.status_code, 302)
        payments = Payment.objects.filter(title="Curso").order_by("installment_number")
        self.assertEqual(payments.count(), 5)
        self.assertEqual([payment.installment_number for payment in payments], [1, 2, 3, 4, 5])
        self.assertEqual(
            [payment.payment_date for payment in payments],
            [date(2026, 6, 5), date(2026, 7, 5), date(2026, 8, 5), date(2026, 9, 5), date(2026, 10, 5)],
        )
        self.assertEqual(len({payment.installment_group for payment in payments}), 1)

    def test_installment_current_number_cannot_exceed_total(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:create"),
            {
                "title": "Compra inválida",
                "category": self.category.pk,
                "amount": "120,00",
                "payment_method": self.card_method.pk,
                "is_installment": "on",
                "installment_total": "3",
                "installment_number": "4",
                "payment_date": "2026-08-05",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A parcela atual não pode ser maior que o total de parcelas.")
        self.assertFalse(Payment.objects.filter(title="Compra inválida").exists())

    def test_future_installments_are_separated_from_current_payment_list(self):
        today = timezone.localdate()
        self.client.force_login(self.user)
        self.client.post(
            reverse("payments:create"),
            {
                "title": "Geladeira",
                "category": self.category.pk,
                "amount": "200,00",
                "payment_method": self.card_method.pk,
                "is_installment": "on",
                "installment_total": "3",
                "installment_number": "1",
                "payment_date": today.isoformat(),
            },
        )

        response = self.client.get(reverse("payments:list"))

        self.assertEqual([payment.installment_number for payment in response.context["payments"]], [1])
        self.assertEqual([payment.installment_number for payment in response.context["future_installments"]], [2, 3])
        self.assertContains(response, "Lançamentos futuros")
