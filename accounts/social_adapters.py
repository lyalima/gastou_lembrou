from allauth.account.models import EmailAddress
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class SocialAccountAdapter(DefaultSocialAccountAdapter):
    trusted_email_providers = {"google"}

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
