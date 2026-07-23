from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .forms import SupportForm


User = get_user_model()


class SupportTests(TestCase):
    def create_verified_user(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        LegalAcceptance.objects.create(
            user=user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )
        return user

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Gastou Lembrou <principal@example.com>",
        SUPPORT_EMAIL="help@example.com",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_support_form_sends_email(self):
        user = self.create_verified_user()
        self.client.force_login(user)

        response = self.client.post(
            reverse("support:home"),
            {"nome": "Ana", "email": "ana@example.com", "problema": "Preciso de ajuda."},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].from_email, "Gastou Lembrou <principal@example.com>")
        self.assertEqual(mail.outbox[0].to, ["help@example.com"])
        self.assertEqual(mail.outbox[0].reply_to, ["ana@example.com"])
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Nova mensagem de suporte", mail.outbox[0].alternatives[0][0])
        self.assertIn("/static/img/gastou-lembrou-logo.png", mail.outbox[0].alternatives[0][0])
        self.assertEqual(mail.outbox[0].attachments, [])

    def test_support_email_field_is_readonly(self):
        user = self.create_verified_user()
        self.client.force_login(user)

        response = self.client.get(reverse("support:home"))

        self.assertContains(response, 'name="email"')
        self.assertContains(response, "readonly")

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="Gastou Lembrou <principal@example.com>",
        SUPPORT_EMAIL="help@example.com",
        CELERY_TASK_ALWAYS_EAGER=True,
    )
    def test_support_form_uses_authenticated_user_email(self):
        user = self.create_verified_user()
        self.client.force_login(user)

        response = self.client.post(
            reverse("support:home"),
            {"nome": "Ana", "email": "outro@example.com", "problema": "Preciso de ajuda."},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(mail.outbox[0].from_email, "Gastou Lembrou <principal@example.com>")
        self.assertEqual(mail.outbox[0].reply_to, ["ana@example.com"])

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SUPPORT_EMAIL="help@example.com", CELERY_TASK_ALWAYS_EAGER=True)
    def test_support_form_sends_email_with_screenshot_attachment(self):
        user = self.create_verified_user()
        self.client.force_login(user)
        screenshot = SimpleUploadedFile("erro.png", _png_bytes(), content_type="image/png")

        response = self.client.post(
            reverse("support:home"),
            {"nome": "Ana", "email": "ana@example.com", "problema": "Tela com erro.", "screenshot": screenshot},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        filenames = [attachment[0] for attachment in mail.outbox[0].attachments if isinstance(attachment, tuple)]
        self.assertIn("erro.png", filenames)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")

    def test_support_form_rejects_screenshot_with_invalid_content_type(self):
        screenshot = SimpleUploadedFile("erro.webp", _png_bytes(), content_type="image/webp")

        form = SupportForm(
            data={"nome": "Ana", "email": "ana@example.com", "problema": "Tela com erro."},
            files={"screenshot": screenshot},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("screenshot", form.errors)

    def test_support_form_rejects_screenshot_with_invalid_extension(self):
        screenshot = SimpleUploadedFile("erro.gif", _png_bytes(), content_type="image/png")

        form = SupportForm(
            data={"nome": "Ana", "email": "ana@example.com", "problema": "Tela com erro."},
            files={"screenshot": screenshot},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("screenshot", form.errors)


def _png_bytes():
    return (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04"
        b"\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
