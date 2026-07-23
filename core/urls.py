from django.urls import path

from .views import HomeView, ManifestView, OfflineView, PrivacyView, ServiceWorkerView, TermsView

app_name = "core"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("manifest.webmanifest", ManifestView.as_view(), name="manifest"),
    path("service-worker.js", ServiceWorkerView.as_view(), name="service_worker"),
    path("offline/", OfflineView.as_view(), name="offline"),
    path("termos-de-uso/", TermsView.as_view(), name="terms"),
    path("politica-de-privacidade/", PrivacyView.as_view(), name="privacy"),
]
