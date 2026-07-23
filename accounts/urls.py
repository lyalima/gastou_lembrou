from django.urls import path

from .views import AccountDeleteView, AccountPasswordChangeView, LegalUpdateAcceptanceView, ProfileView

app_name = "accounts"

urlpatterns = [
    path("", ProfileView.as_view(), name="profile"),
    path("aceite-legal/", LegalUpdateAcceptanceView.as_view(), name="legal_acceptance"),
    path("senha/", AccountPasswordChangeView.as_view(), name="password_change"),
    path("excluir/", AccountDeleteView.as_view(), name="delete"),
]
