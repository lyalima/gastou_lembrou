from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from .legal import needs_legal_update_acceptance
from .tasks import queue_legal_update_notification


class LegalAcceptanceRequiredMiddleware:
    allowed_url_names = {
        "legal_acceptance",
        "terms",
        "privacy",
        "account_logout",
        "account_login",
        "account_signup",
        "account_email_verification_sent",
        "account_confirm_email",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_redirect(request):
            queue_legal_update_notification(request.user.pk)
            return redirect("accounts:legal_acceptance")
        return self.get_response(request)

    def _must_redirect(self, request):
        user = getattr(request, "user", None)
        if not getattr(user, "is_authenticated", False):
            return False
        static_prefix = "/" + settings.STATIC_URL.lstrip("/")
        media_prefix = "/" + settings.MEDIA_URL.lstrip("/")
        if request.path.startswith((static_prefix, media_prefix, "/admin/")):
            return False
        resolver_match = getattr(request, "resolver_match", None)
        if resolver_match is None:
            try:
                resolver_match = resolve(request.path_info)
            except Resolver404:
                resolver_match = None
        if resolver_match and resolver_match.url_name in self.allowed_url_names:
            return False
        if request.path == reverse("accounts:legal_acceptance"):
            return False
        return needs_legal_update_acceptance(user)
