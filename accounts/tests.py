import json
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.conf import settings
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from allauth.account.models import EmailAddress
from allauth.account.signals import email_confirmed
from allauth.socialaccount.models import SocialAccount, SocialLogin

from core.emails import email_brand_context, serialize_email_message
from payments.models import Category, Payment

from .forms import AccountSignupForm, GoogleSignupForm, ManualAccountResetPasswordKeyForm, ProfileForm
from .legal import PRIVACY_VERSION, TERMS_VERSION
from .models import LegalAcceptance, LegalUpdateNotification
from .social_adapters import SocialAccountAdapter
from .validators import validate_cpf, validate_phone


User = get_user_model()


class UserModelTests(TestCase):
    def accept_current_legal_terms(self, user):
        return LegalAcceptance.objects.create(
            user=user,
            terms_version=TERMS_VERSION,
            privacy_version=PRIVACY_VERSION,
            source=LegalAcceptance.Source.EMAIL,
        )

    def test_user_uses_email_without_username(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345")

        self.assertEqual(user.USERNAME_FIELD, "email")
        self.assertNotIn("username", [field.name for field in User._meta.fields])
        self.assertEqual(user.email, "ana@example.com")

    def test_cpf_and_phone_validation(self):
        validate_cpf("529.982.247-25")
        validate_phone("(11) 99999-9999")
        validate_phone("+5511999999999")

        with self.assertRaises(ValidationError):
            validate_cpf("111.111.111-11")
        with self.assertRaises(ValidationError):
            validate_phone("119999")

    def test_profile_form_blocks_existing_cpf_change(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", cpf="529.982.247-25")
        form = ProfileForm(
            data={"email": "ana@example.com", "telefone": "(11) 99999-9999", "cpf": "390.533.447-05"},
            instance=user,
            user=user,
        )

        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["cpf"], "529.982.247-25")

    def test_profile_phone_field_has_frontend_length_limit(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345")

        form = ProfileForm(instance=user, user=user)

        self.assertEqual(form.fields["telefone"].widget.attrs["maxlength"], "20")
        self.assertEqual(form.fields["telefone"].widget.attrs["data-phone-limit"], "true")

    def test_profile_form_rejects_too_long_phone(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345")
        form = ProfileForm(
            data={"email": "ana@example.com", "telefone": "+551199999999999999", "cpf": ""},
            instance=user,
            user=user,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("telefone", form.errors)

    def test_profile_displays_permanent_account_delete_action(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.accept_current_legal_terms(user)
        self.client.force_login(user)

        response = self.client.get(reverse("accounts:profile"))

        self.assertContains(response, "Excluir minha conta")
        self.assertContains(response, reverse("accounts:delete"))

    @patch("accounts.middleware.queue_legal_update_notification")
    def test_user_with_old_legal_acceptance_is_redirected_to_new_acceptance(self, queue_notification):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        LegalAcceptance.objects.create(
            user=user,
            terms_version="2026-01-01",
            privacy_version="2026-01-01",
            source=LegalAcceptance.Source.EMAIL,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("payments:list"))

        self.assertRedirects(response, reverse("accounts:legal_acceptance"))
        queue_notification.assert_called_once_with(user.pk)

    def test_user_accepts_updated_terms_and_can_continue(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        LegalAcceptance.objects.create(
            user=user,
            terms_version="2026-01-01",
            privacy_version="2026-01-01",
            source=LegalAcceptance.Source.EMAIL,
        )
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:legal_acceptance"),
            {"accept_terms": "on", "acknowledge_privacy": "on"},
        )

        self.assertRedirects(response, reverse("payments:list"))
        self.assertTrue(
            LegalAcceptance.objects.filter(
                user=user,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
                source=LegalAcceptance.Source.UPDATE,
            ).exists()
        )

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_legal_update_notification_email_is_sent_once(self):
        from .tasks import send_legal_update_notification

        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        LegalAcceptance.objects.create(
            user=user,
            terms_version="2026-01-01",
            privacy_version="2026-01-01",
            source=LegalAcceptance.Source.EMAIL,
        )

        first_result = send_legal_update_notification(str(user.pk))
        second_result = send_legal_update_notification(str(user.pk))

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("Atualização dos Termos", mail.outbox[0].subject)
        self.assertEqual(
            LegalUpdateNotification.objects.filter(
                user=user,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
            ).count(),
            1,
        )

    def test_account_delete_requires_exact_confirmation(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.accept_current_legal_terms(user)
        self.client.force_login(user)

        response = self.client.post(reverse("accounts:delete"), {"confirmation": "excluir"})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(User.objects.filter(pk=user.pk).exists())
        self.assertContains(response, "Digite exatamente")
        self.assertContains(response, "EXCLUIR")

    def test_account_delete_removes_user_payments_receipt_and_session(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
            category = Category.objects.create(name="Mercado")
            payment = Payment.objects.create(
                user=user,
                category=category,
                title="Compra",
                amount="25.00",
                image=SimpleUploadedFile("nota.png", b"arquivo", content_type="image/png"),
            )
            self.accept_current_legal_terms(user)
            receipt_path = payment.image.path
            self.assertTrue(os.path.exists(receipt_path))
            self.client.force_login(user)

            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse("accounts:delete"), {"confirmation": "EXCLUIR"})

            self.assertRedirects(response, reverse("core:home"))
            self.assertFalse(User.objects.filter(pk=user.pk).exists())
            self.assertFalse(Payment.objects.filter(pk=payment.pk).exists())
            self.assertFalse(os.path.exists(receipt_path))
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_email_confirmed_signal_marks_user_verified(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=False)
        email_address = EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)

        email_confirmed.send(sender=self.__class__, request=None, email_address=email_address)

        user.refresh_from_db()
        self.assertTrue(user.email_verified)

    def test_email_confirmed_signal_syncs_new_email_for_login(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=False)
        EmailAddress.objects.create(user=user, email="ana@example.com", primary=True, verified=True)
        email_address = EmailAddress.objects.create(user=user, email="novo@example.com", primary=False, verified=True)

        email_confirmed.send(sender=self.__class__, request=None, email_address=email_address)

        user.refresh_from_db()
        email_address.refresh_from_db()
        self.assertEqual(user.email, "novo@example.com")
        self.assertTrue(user.email_verified)
        self.assertTrue(email_address.primary)
        self.assertFalse(EmailAddress.objects.filter(user=user, email="ana@example.com").exists())
        self.assertEqual(authenticate(email="novo@example.com", password="pass12345"), user)

    def test_email_confirmed_signal_logs_user_in_when_request_is_anonymous(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=False)
        email_address = EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        request = RequestFactory().get("/")
        request.session = self.client.session
        request.user = type("Anonymous", (), {"is_authenticated": False})()

        email_confirmed.send(sender=self.__class__, request=request, email_address=email_address)

        self.assertEqual(str(request.session["_auth_user_id"]), str(user.pk))

    @patch("allauth.account.models.EmailAddress.send_confirmation")
    def test_profile_email_change_sends_confirmation_and_logs_user_out(self, send_confirmation):
        user = User.objects.create_user(
            email="ana@example.com",
            password="pass12345",
            email_verified=True,
            telefone="+5511999999999",
        )
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        self.accept_current_legal_terms(user)
        self.client.force_login(user)

        response = self.client.post(
            reverse("accounts:profile"),
            {"email": "novo@example.com", "telefone": "+5511999999999", "cpf": ""},
        )

        user.refresh_from_db()
        new_email_address = EmailAddress.objects.get(user=user, email="novo@example.com")
        self.assertRedirects(response, reverse("account_email_verification_sent"))
        self.assertEqual(user.email, "novo@example.com")
        self.assertFalse(user.email_verified)
        self.assertTrue(new_email_address.primary)
        self.assertFalse(new_email_address.verified)
        self.assertFalse(EmailAddress.objects.filter(user=user, email="ana@example.com").exists())
        send_confirmation.assert_called_once()
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_allauth_confirmation_html_templates_render_brand_and_link(self):
        context = {**email_brand_context(), "activate_url": "https://example.com/confirmar/"}

        confirmation_html = render_to_string("account/email/email_confirmation_message.html", context)
        signup_html = render_to_string("account/email/email_confirmation_signup_message.html", context)

        self.assertIn("Gastou, Lembrou!", confirmation_html)
        self.assertIn("https://example.com/confirmar/", confirmation_html)
        self.assertIn("Ative sua conta", signup_html)
        self.assertIn("https://example.com/confirmar/", signup_html)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_signup_confirmation_email_is_sent_through_celery_task(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "nova@example.com",
                "password1": "pass12345forte",
                "password2": "pass12345forte",
                "accept_terms": "on",
                "acknowledge_privacy": "on",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Confirme seu email no Gastou Lembrou")
        self.assertNotIn("example.com", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("http://127.0.0.1:8000/static/img/gastou-lembrou-logo.png", mail.outbox[0].alternatives[0][0])
        self.assertEqual(mail.outbox[0].attachments, [])

    @override_settings(
        EMAIL_ASSET_BASE_URL="http://127.0.0.1:8000",
        SITE_URL="http://web:8000",
        PROJECT_EMAIL_SITE_NAME="Gastou, Lembrou!",
    )
    def test_email_logo_uses_public_asset_base_url(self):
        context = {**email_brand_context(), "title": "Teste", "preheader": "", "body": "Conteudo"}

        html = render_to_string("emails/message.html", context)

        self.assertIn("http://127.0.0.1:8000/static/img/gastou-lembrou-logo.png", html)
        self.assertNotIn("http://web:8000/static/img/gastou-lembrou-logo.png", html)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_signup_confirmation_email_payload_is_json_serializable(self):
        self.client.post(
            reverse("account_signup"),
            {
                "email": "json@example.com",
                "password1": "pass12345forte",
                "password2": "pass12345forte",
                "accept_terms": "on",
                "acknowledge_privacy": "on",
            },
        )

        payload = serialize_email_message(mail.outbox[0])

        json.dumps(payload)
        self.assertEqual(payload["alternatives"][0]["mimetype"], "text/html")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_signup_requires_terms_and_privacy_acknowledgement(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "sem-aceite@example.com",
                "password1": "pass12345forte",
                "password2": "pass12345forte",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email="sem-aceite@example.com").exists())
        self.assertContains(response, "Você precisa aceitar os Termos de Uso")
        self.assertContains(response, "Você precisa declarar ciência da Política de Privacidade")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_signup_records_versioned_legal_acceptance(self):
        response = self.client.post(
            reverse("account_signup"),
            {
                "email": "aceite@example.com",
                "password1": "pass12345forte",
                "password2": "pass12345forte",
                "accept_terms": "on",
                "acknowledge_privacy": "on",
            },
            REMOTE_ADDR="203.0.113.10",
            HTTP_USER_AGENT="Browser de teste",
        )

        user = User.objects.get(email="aceite@example.com")
        acceptance = LegalAcceptance.objects.get(user=user)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(acceptance.terms_version, TERMS_VERSION)
        self.assertEqual(acceptance.privacy_version, PRIVACY_VERSION)
        self.assertEqual(acceptance.source, LegalAcceptance.Source.EMAIL)
        self.assertEqual(str(acceptance.ip_address), "203.0.113.10")
        self.assertEqual(acceptance.user_agent, "Browser de teste")

    def test_signup_forms_expose_required_legal_fields(self):
        account_form = AccountSignupForm()
        self.assertTrue(account_form.fields["accept_terms"].required)
        self.assertTrue(account_form.fields["acknowledge_privacy"].required)
        self.assertIn("Termos de Uso", str(account_form.fields["accept_terms"].label))

        social_form = GoogleSignupForm(
            sociallogin=SocialLogin(
                user=User(email="google@example.com"),
                account=SocialAccount(provider="google", uid="google-legal"),
                email_addresses=[EmailAddress(email="google@example.com", verified=True, primary=True)],
            )
        )
        self.assertTrue(social_form.fields["accept_terms"].required)
        self.assertTrue(social_form.fields["acknowledge_privacy"].required)

    def test_google_signup_form_records_legal_acceptance(self):
        sociallogin = SocialLogin(
            user=User(email="google-aceite@example.com"),
            account=SocialAccount(provider="google", uid="google-legal-acceptance"),
            email_addresses=[EmailAddress(email="google-aceite@example.com", verified=True, primary=True)],
        )
        form = GoogleSignupForm(
            data={
                "email": "google-aceite@example.com",
                "accept_terms": "on",
                "acknowledge_privacy": "on",
            },
            sociallogin=sociallogin,
        )
        request = RequestFactory().post("/accounts/3rdparty/signup/")
        request.session = self.client.session

        self.assertTrue(form.is_valid(), form.errors)
        user = form.save(request)

        acceptance = LegalAcceptance.objects.get(user=user)
        self.assertEqual(acceptance.source, LegalAcceptance.Source.GOOGLE)
        self.assertEqual(acceptance.terms_version, TERMS_VERSION)
        self.assertEqual(acceptance.privacy_version, PRIVACY_VERSION)

    def test_google_provider_allows_email_authentication(self):
        self.assertEqual(settings.SOCIALACCOUNT_ADAPTER, "accounts.social_adapters.SocialAccountAdapter")
        self.assertTrue(settings.SOCIALACCOUNT_PROVIDERS["google"]["EMAIL_AUTHENTICATION"])
        self.assertFalse(settings.SOCIALACCOUNT_AUTO_SIGNUP)
        self.assertEqual(settings.SOCIALACCOUNT_FORMS["signup"], "accounts.forms.GoogleSignupForm")

    def test_login_shows_password_reset_link(self):
        response = self.client.get(reverse("account_login"))

        self.assertContains(response, "Esqueci minha senha")
        self.assertContains(response, reverse("account_reset_password"))

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_manual_account_can_request_password_reset(self):
        user = User.objects.create_user(email="manual@example.com", password="pass12345forte", email_verified=True)
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)

        response = self.client.post(reverse("account_reset_password"), {"email": user.email})

        self.assertRedirects(response, reverse("account_reset_password_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Redefinição de senha no Gastou Lembrou")
        self.assertNotIn("example.com", mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Criar nova senha", mail.outbox[0].alternatives[0][0])
        self.assertIn("/accounts/password/reset/key/", mail.outbox[0].body)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", CELERY_TASK_ALWAYS_EAGER=True)
    def test_social_only_account_does_not_receive_password_reset_email(self):
        user = User.objects.create_user(email="google-only@example.com", password=None, email_verified=True)
        EmailAddress.objects.create(user=user, email=user.email, primary=True, verified=True)
        SocialAccount.objects.create(user=user, provider="google", uid="google-only")

        response = self.client.post(reverse("account_reset_password"), {"email": user.email})

        self.assertRedirects(response, reverse("account_reset_password_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_new_password_uses_project_validators(self):
        user = User.objects.create_user(email="manual@example.com", password="pass12345forte", email_verified=True)
        form = ManualAccountResetPasswordKeyForm(user=user, data={"password1": "123", "password2": "123"})

        self.assertFalse(form.is_valid())
        self.assertIn("password1", form.errors)

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {"client_id": "google-client-id", "secret": "google-secret", "key": ""},
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "EMAIL_AUTHENTICATION": True,
            }
        }
    )
    def test_login_and_signup_show_google_buttons_when_configured(self):
        login_response = self.client.get(reverse("account_login"))
        signup_response = self.client.get(reverse("account_signup"))

        self.assertContains(login_response, "Entrar com Google")
        self.assertContains(signup_response, "Cadastrar com Google")
        self.assertContains(signup_response, "Termos de Uso")
        self.assertContains(signup_response, "Política de Privacidade")
        self.assertContains(login_response, "/accounts/google/login/")
        self.assertContains(signup_response, "/accounts/google/login/")

    @override_settings(
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {"client_id": "google-client-id", "secret": "google-secret", "key": ""},
                "SCOPE": ["profile", "email"],
                "AUTH_PARAMS": {"access_type": "online"},
                "EMAIL_AUTHENTICATION": True,
            }
        }
    )
    def test_google_login_confirmation_page_uses_styled_template(self):
        response = self.client.get("/accounts/google/login/")

        self.assertContains(response, "auth-card")
        self.assertContains(response, "Continuar com Google")
        self.assertContains(response, "Voltar para login")
        self.assertTemplateUsed(response, "socialaccount/login.html")

    def test_social_adapter_marks_google_verified_email_on_signup(self):
        user = User(email="social@example.com", email_verified=False)
        sociallogin = SocialLogin(
            user=user,
            account=SocialAccount(provider="google", uid="google-123"),
            email_addresses=[EmailAddress(email="social@example.com", verified=True, primary=True)],
        )

        request = RequestFactory().get("/")
        request.session = self.client.session

        SocialAccountAdapter().save_user(request, sociallogin)

        user.refresh_from_db()
        email_address = EmailAddress.objects.get(user=user, email="social@example.com")
        self.assertTrue(user.email_verified)
        self.assertTrue(email_address.verified)
        self.assertTrue(email_address.primary)

    def test_social_adapter_ignores_unverified_google_email(self):
        user = User.objects.create_user(email="social@example.com", password="pass12345", email_verified=False)
        sociallogin = SocialLogin(
            user=user,
            account=SocialAccount(provider="google", uid="google-123"),
            email_addresses=[EmailAddress(email="social@example.com", verified=False, primary=True)],
        )

        SocialAccountAdapter().pre_social_login(RequestFactory().get("/"), sociallogin)

        user.refresh_from_db()
        self.assertFalse(user.email_verified)
