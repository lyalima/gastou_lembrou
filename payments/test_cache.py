from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .models import Category, Payment


User = get_user_model()


class PaymentListCacheTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Mercado")
        LegalAcceptance.objects.create(
            user=self.user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )
        cache.clear()

    def test_payment_list_cache_is_invalidated_after_payment_changes(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta inicial",
            amount=Decimal("20.00"),
            payment_date=date(2026, 5, 1),
        )

        self.client.force_login(self.user)
        first_response = self.client.get(reverse("payments:list"))
        self.assertContains(first_response, "Conta inicial")

        with self.captureOnCommitCallbacks(execute=True):
            Payment.objects.create(
                user=self.user,
                category=self.category,
                title="Conta nova",
                amount=Decimal("35.00"),
                payment_date=date(2026, 5, 2),
            )
        second_response = self.client.get(reverse("payments:list"))
        self.assertContains(second_response, "Conta nova")

        with self.captureOnCommitCallbacks(execute=True):
            payment.delete()
        third_response = self.client.get(reverse("payments:list"))
        self.assertNotContains(third_response, "Conta inicial")
