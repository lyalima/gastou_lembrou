from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .forms import UserCreationForm, UserChangeForm
from .models import LegalAcceptance, LegalUpdateNotification, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    add_form = UserCreationForm
    form = UserChangeForm
    model = User
    list_display = ("email", "cpf", "telefone", "email_verified", "is_staff", "is_active")
    list_filter = ("email_verified", "is_staff", "is_active")
    ordering = ("email",)
    search_fields = ("email", "cpf", "telefone")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Dados pessoais", {"fields": ("cpf", "telefone", "email_verified")}),
        ("Permissões", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Datas", {"fields": ("last_login", "created_at", "updated_at")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "password1", "password2", "is_staff", "is_active")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login")


@admin.register(LegalAcceptance)
class LegalAcceptanceAdmin(admin.ModelAdmin):
    list_display = ("user", "terms_version", "privacy_version", "source", "accepted_at", "ip_address")
    list_filter = ("source", "terms_version", "privacy_version")
    search_fields = ("user__email", "ip_address")
    readonly_fields = (
        "user",
        "terms_version",
        "privacy_version",
        "source",
        "accepted_at",
        "ip_address",
        "user_agent",
    )


@admin.register(LegalUpdateNotification)
class LegalUpdateNotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "terms_version", "privacy_version", "notified_at")
    list_filter = ("terms_version", "privacy_version", "notified_at")
    search_fields = ("user__email",)
    readonly_fields = ("user", "terms_version", "privacy_version", "notified_at")
