import uuid

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

from .managers import UserManager
from .validators import validate_cpf, validate_phone


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    cpf = models.CharField(max_length=14, unique=True, blank=True, null=True, validators=[validate_cpf])
    telefone = models.CharField(max_length=32, unique=True, blank=True, null=True, validators=[validate_phone])
    email_verified = models.BooleanField(default=False)
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    username = None
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def initials(self):
        return (self.email[:2] if self.email else "GL").upper()


class LegalAcceptance(models.Model):
    class Source(models.TextChoices):
        EMAIL = "email", "Cadastro por email"
        GOOGLE = "google", "Cadastro com Google"
        UPDATE = "update", "Atualização de termos"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="legal_acceptances")
    terms_version = models.CharField(max_length=20)
    privacy_version = models.CharField(max_length=20)
    source = models.CharField(max_length=16, choices=Source.choices)
    accepted_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ("-accepted_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "terms_version", "privacy_version"),
                name="unique_legal_acceptance_per_version",
            )
        ]

    def __str__(self):
        return f"{self.user} - termos {self.terms_version}"


class LegalUpdateNotification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="legal_update_notifications")
    terms_version = models.CharField(max_length=20)
    privacy_version = models.CharField(max_length=20)
    notified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-notified_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "terms_version", "privacy_version"),
                name="unique_legal_update_notification_per_version",
            )
        ]

    def __str__(self):
        return f"{self.user} - aviso legal {self.terms_version}/{self.privacy_version}"
