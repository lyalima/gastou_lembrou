from decimal import Decimal
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .forms import CreditCardStatementImportForm, PaymentForm
from .models import Category, Payment


User = get_user_model()


class PaymentSecurityTests(TestCase):
    def setUp(self):
        self.user = self.create_user("ana@example.com")
        self.other = self.create_user("bia@example.com")
        self.category = Category.objects.create(name="Mercado")

    def create_user(self, email):
        user = User.objects.create_user(email=email, password="pass12345forte", email_verified=True)
        LegalAcceptance.objects.create(
            user=user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )
        return user

    def test_receipt_file_requires_payment_owner(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            payment = Payment.objects.create(
                user=self.user,
                category=self.category,
                title="Nota privada",
                amount=Decimal("20.00"),
                image=SimpleUploadedFile("nota.png", _png_bytes(), content_type="image/png"),
            )

            self.client.force_login(self.other)
            response = self.client.get(reverse("payments:receipt", kwargs={"pk": payment.pk}))

        self.assertEqual(response.status_code, 404)

    def test_receipt_rejects_file_with_fake_signature(self):
        form = PaymentForm(
            user=self.user,
            data={"title": "Arquivo falso", "category": self.category.pk, "amount": "10.00"},
            files={"image": SimpleUploadedFile("nota.pdf", b"not-a-pdf", content_type="application/pdf")},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    @override_settings(MAX_CREDIT_CARD_STATEMENT_UPLOAD_MB=1)
    def test_credit_card_statement_rejects_large_file(self):
        upload = SimpleUploadedFile("fatura.pdf", b"%PDF-" + (b"0" * (1024 * 1024 + 1)), content_type="application/pdf")
        form = CreditCardStatementImportForm(files={"statement_file": upload})

        self.assertFalse(form.is_valid())
        self.assertIn("statement_file", form.errors)


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04"
        b"\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
