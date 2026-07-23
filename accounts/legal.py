from django.conf import settings


TERMS_VERSION = "2026-07-16"
PRIVACY_VERSION = "2026-07-16"
TERMS_EFFECTIVE_DATE = "16 de julho de 2026"
PRIVACY_EFFECTIVE_DATE = "16 de julho de 2026"


def legal_context():
    return {
        "terms_version": TERMS_VERSION,
        "privacy_version": PRIVACY_VERSION,
        "terms_effective_date": TERMS_EFFECTIVE_DATE,
        "privacy_effective_date": PRIVACY_EFFECTIVE_DATE,
        "privacy_contact_email": settings.SUPPORT_EMAIL,
    }


def client_ip(request):
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.META.get("REMOTE_ADDR") or None


def register_legal_acceptance(user, request, source):
    from .models import LegalAcceptance

    return LegalAcceptance.objects.get_or_create(
        user=user,
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
        defaults={
            "source": source,
            "ip_address": client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:500],
        },
    )[0]


def has_current_legal_acceptance(user):
    if not getattr(user, "is_authenticated", False):
        return True
    return user.legal_acceptances.filter(
        terms_version=TERMS_VERSION,
        privacy_version=PRIVACY_VERSION,
    ).exists()


def needs_legal_update_acceptance(user):
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return False
    return not has_current_legal_acceptance(user)
