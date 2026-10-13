import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from payments.models import Payment

from .crypto import decrypt_value, encrypt_value


class AssistantConversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Ativa"
        CLOSED = "closed", "Encerrada"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_conversations")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    closed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user",),
                condition=Q(status="active"),
                name="unique_active_spike_conversation_per_user",
            )
        ]

    def close(self):
        if self.status != self.Status.CLOSED:
            self.status = self.Status.CLOSED
            self.closed_at = timezone.now()
            self.save(update_fields=("status", "closed_at", "updated_at"))

    def __str__(self):
        return f"Spike - {self.user} - {self.get_status_display()}"


class AssistantPaymentAction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(AssistantConversation, on_delete=models.CASCADE, related_name="payment_actions")
    operation = models.CharField(max_length=10, choices=[("create", "Criar"), ("update", "Editar")])
    payload = models.JSONField()
    payment = models.ForeignKey(Payment, on_delete=models.SET_NULL, null=True, blank=True)
    expected_updated_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    status = models.CharField(max_length=12, default="pending", choices=[("pending", "Pendente"), ("confirmed", "Confirmado"), ("cancelled", "Cancelado")])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def review_fields(self):
        from datetime import date
        from payments.card_cycles import statement_due_date
        from payments.classification import normalize_text
        from payments.models import Category, CreditCard, PaymentMethod
        labels = {"title": "Título", "amount": "Valor (R$)", "description": "Descrição", "payment_date": "Data de pagamento", "scheduled_date": "Data prevista", "category": "Categoria", "payment_method": "Forma de pagamento", "credit_card": "Cartão", "is_installment": "Parcelado", "installment_total": "Total de parcelas", "installment_number": "Parcela atual", "is_recurring": "Recorrente", "recurrence_frequency": "Frequência"}
        method = PaymentMethod.objects.filter(pk=self.payload.get("payment_method")).first() if self.payload.get("payment_method") else None
        if method and normalize_text(method.name) in {"cartao de credito", "cartao credito", "credito"}:
            labels["payment_date"] = "Data da compra"
        result = []
        for field, value in self.payload.items():
            if value not in (None, "") and field in {"category", "credit_card", "payment_method"}:
                queryset = {"category": Category.objects.filter(Q(user=self.user) | Q(user__isnull=True)), "credit_card": CreditCard.objects.filter(user=self.user), "payment_method": PaymentMethod.objects.all()}[field]
                value = queryset.filter(pk=value).values_list("name", flat=True).first() or "Indisponível"
            elif value and field in {"payment_date", "scheduled_date"}:
                value = date.fromisoformat(value).strftime("%d/%m/%Y")
            elif field in {"is_installment", "is_recurring"}:
                value = "Sim" if value else "Não"
            elif field == "recurrence_frequency":
                value = {1: "Mensal", 3: "Trimestral", 6: "Semestral", 12: "Anual"}.get(value, value)
            result.append({"label": labels.get(field, field), "value": value if value not in (None, "") else "Remover"})
        if self.operation == "create":
            if not self.payload.get("payment_method"):
                result.append({"label": "Forma de pagamento", "value": "Não informada"})
            if not self.payload.get("category"):
                result.append({"label": "Categoria", "value": "Seleção automática"})
            card = CreditCard.objects.filter(pk=self.payload.get("credit_card"), user=self.user).first() if self.payload.get("credit_card") else None
            base_date = self.payload.get("payment_date") or self.payload.get("scheduled_date")
            if card and base_date:
                result.append({"label": "Vencimento da fatura", "value": statement_due_date(card, date.fromisoformat(base_date)).strftime("%d/%m/%Y")})
            if self.payload.get("is_installment"):
                result.append({"label": "Parcelas adicionais a criar", "value": int(self.payload["installment_total"]) - 1})
        return result


class AssistantMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Usuário"
        ASSISTANT = "assistant", "Spike"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="assistant_messages")
    conversation = models.ForeignKey(
        AssistantConversation,
        on_delete=models.CASCADE,
        related_name="messages",
        blank=True,
        null=True,
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField(max_length=2000)
    intent = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"{self.get_role_display()} - {self.user}"


class AssistantKnowledgeDocument(models.Model):
    slug = models.SlugField(max_length=120, unique=True)
    title = models.CharField(max_length=180)
    source_path = models.CharField(max_length=255, unique=True)
    version = models.CharField(max_length=32, default="1.0")
    checksum = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("title",)

    def __str__(self):
        return self.title


class AssistantKnowledgeChunk(models.Model):
    document = models.ForeignKey(AssistantKnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    heading = models.CharField(max_length=220, blank=True)
    content = models.TextField()
    position = models.PositiveIntegerField()
    embedding = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("document", "position")
        constraints = [
            models.UniqueConstraint(fields=("document", "position"), name="unique_spike_chunk_position"),
        ]

    def __str__(self):
        return f"{self.document.title} - {self.heading or self.position}"


class GoogleCalendarConnection(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_calendar_connection")
    google_email = models.EmailField(blank=True)
    access_token_encrypted = models.TextField(blank=True)
    refresh_token_encrypted = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)
    scope = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Conexão com Google Agenda"
        verbose_name_plural = "Conexões com Google Agenda"

    def __str__(self):
        return self.google_email or str(self.user)

    @property
    def access_token(self):
        return decrypt_value(self.access_token_encrypted)

    @access_token.setter
    def access_token(self, value):
        self.access_token_encrypted = encrypt_value(value)

    @property
    def refresh_token(self):
        return decrypt_value(self.refresh_token_encrypted)

    @refresh_token.setter
    def refresh_token(self, value):
        self.refresh_token_encrypted = encrypt_value(value)


class PaymentCalendarEvent(models.Model):
    class Status(models.TextChoices):
        CREATED = "created", "Criado"
        FAILED = "failed", "Falhou"
        DELETED = "deleted", "Excluído"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payment_calendar_events")
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name="calendar_event")
    google_event_id = models.CharField(max_length=255, blank=True)
    calendar_id = models.CharField(max_length=255, default="primary")
    title = models.CharField(max_length=200)
    scheduled_for = models.DateField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.CREATED)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "payment"), name="unique_calendar_event_per_user_payment"),
        ]

    def __str__(self):
        return self.title
