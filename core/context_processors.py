from django.conf import settings
from allauth.socialaccount.models import SocialApp


def oauth_flags(request):
    google_app = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get("APP", {})
    google_app_in_database = SocialApp.objects.filter(provider="google").exists()
    return {
        "google_oauth_configured": google_app_in_database or bool(google_app.get("client_id") and google_app.get("secret")),
    }
