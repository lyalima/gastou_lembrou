from django.urls import path

from .views import SupportView

app_name = "support"

urlpatterns = [
    path("", SupportView.as_view(), name="home"),
]
