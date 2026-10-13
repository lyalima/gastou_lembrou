import logging
import re

from django.conf import settings
from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Error


logger = logging.getLogger(__name__)


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    trusted_email_providers = {"google"}

    def on_authentication_error(self, request, provider, error=None, exception=None, extra_context=None):
        if provider.id == "google":
            stage = "state_missing" if extra_context and "state_id" in extra_context else "callback_error"
            provider_error = "unknown"
            if isinstance(exception, OAuth2Error):
                match = re.search(r'"error"\s*:\s*"([a-z_]+)"', str(exception))
                if match:
                    provider_error = match.group(1)
            logger.warning(
                "Google OAuth failed: stage=%s exception=%s provider_error=%s session_cookie_present=%s",
                stage,
                type(exception).__name__ if exception else "none",
                provider_error,
                settings.SESSION_COOKIE_NAME in request.COOKIES,
            )
        return super().on_authentication_error(request, provider, error, exception, extra_context)

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        self._sync_verified_email(user, sociallogin)
        return user

    def pre_social_login(self, request, sociallogin):
        if sociallogin.is_existing:
            self._sync_verified_email(sociallogin.user, sociallogin)

    def _sync_verified_email(self, user, sociallogin):
        email = self._trusted_email(sociallogin)
        if not email:
            return

        if user.email != email:
            user.email = email
        if not user.email_verified:
            user.email_verified = True
        user.save(update_fields=["email", "email_verified", "updated_at"])

        EmailAddress.objects.update_or_create(
            user=user,
            email=email,
            defaults={"primary": True, "verified": True},
        )
        EmailAddress.objects.filter(user=user).exclude(email=email).update(primary=False)

    def _trusted_email(self, sociallogin):
        if sociallogin.account.provider not in self.trusted_email_providers:
            return ""
        for email_address in sociallogin.email_addresses:
            if email_address.email and email_address.verified:
                return email_address.email
        return ""
