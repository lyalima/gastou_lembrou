from django.conf import settings
from django.shortcuts import redirect
from django.urls import Resolver404, resolve, reverse

from .legal import needs_legal_update_acceptance
from .tasks import queue_legal_update_notification


class AbsoluteSessionLifetimeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib.auth import logout
        from django.http import HttpResponse
        from django.utils import timezone
        from django.utils.cache import add_never_cache_headers

        authenticated = request.user.is_authenticated
        if authenticated:
            deadline = request.session.get("auth_expires_at")
            # Sessions created before this policy must authenticate again.
            if not isinstance(deadline, (float, int)) or timezone.now().timestamp() >= deadline:
                logout(request)
                response = redirect("account_login")
            else:
                response = self.get_response(request)
        else:
            response = self.get_response(request)
        if request.headers.get("HX-Request") and response.status_code in (301, 302) and response.get("Location", "").startswith(reverse("account_login")):
            location = response["Location"]
            response = HttpResponse(status=200)
            response["HX-Redirect"] = location
        if authenticated or request.user.is_authenticated:
            add_never_cache_headers(response)
        return response


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
