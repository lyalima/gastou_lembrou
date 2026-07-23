import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone


class Category(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="categories",
        blank=True,
        null=True,
    )
    name = models.CharField(max_length=100)
    description = models.TextField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class PaymentMethod(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class CreditCardStatement(models.Model):
    class Status(models.TextChoices):
        PROCESSING = "processing", "Processando"
        READY = "ready", "Pronto para revisão"
        CONFIRMED = "confirmed", "Importado"
        FAILED = "failed", "Falha"

    class ParserSource(models.TextChoices):
        TEXT = "text", "Texto do PDF"
        GEMINI = "gemini", "Gemini"
        REGEX = "regex", "Leitura local"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="credit_card_statements")
    file = models.FileField(upload_to="payments/credit_card_statements/")
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.PROCESSING)
    parser_source = models.CharField(max_length=24, choices=ParserSource.choices, blank=True)
    extracted_text = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Fatura de cartão - {self.user}"


class Payment(models.Model):
    class Kind(models.TextChoices):
        EXPENSE = "expense", "Gasto comum"
        CREDIT_CARD_BILL = "credit_card_bill", "Pagamento de fatura"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="payments")
    title = models.CharField(max_length=200)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="payments",
        blank=True,
        null=True,
    )
    description = models.TextField(max_length=200, blank=True)
    kind = models.CharField(max_length=32, choices=Kind.choices, default=Kind.EXPENSE)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_method = models.ForeignKey(PaymentMethod, on_delete=models.PROTECT, related_name="payments", blank=True, null=True)
    is_installment = models.BooleanField(default=False)
    payment_date = models.DateField(blank=True, null=True)
    scheduled_date = models.DateField(blank=True, null=True)
    image = models.FileField(upload_to="payments/receipts/", blank=True, null=True)
    import_hash = models.CharField(max_length=64, blank=True, db_index=True)
    imported_at = models.DateTimeField(blank=True, null=True)
    credit_card_statement = models.ForeignKey(
        CreditCardStatement,
        on_delete=models.SET_NULL,
        related_name="payments",
        blank=True,
        null=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-payment_date", "-created_at")
        indexes = [
            models.Index(fields=["user", "payment_date"]),
            models.Index(fields=["user", "scheduled_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "import_hash"],
                condition=~models.Q(import_hash=""),
                name="unique_imported_payment_per_user",
            ),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse("payments:detail", kwargs={"pk": self.pk})

    @property
    def receipt_is_pdf(self):
        return bool(self.image and self.image.name.lower().endswith(".pdf"))

    @property
    def is_credit_card_bill(self):
        return self.kind == self.Kind.CREDIT_CARD_BILL

    @property
    def counts_as_expense(self):
        return self.kind == self.Kind.EXPENSE

    @property
    def is_schedule_finished(self):
        return bool(self.scheduled_date and self.scheduled_date < timezone.localdate())


class CreditCardStatementItem(models.Model):
    class Status(models.TextChoices):
        DETECTED = "detected", "Detectado"
        IMPORTED = "imported", "Importado"
        SKIPPED = "skipped", "Ignorado"

    statement = models.ForeignKey(CreditCardStatement, on_delete=models.CASCADE, related_name="items")
    payment = models.OneToOneField(Payment, on_delete=models.SET_NULL, related_name="statement_item", blank=True, null=True)
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    payment_date = models.DateField()
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, related_name="credit_card_statement_items", blank=True, null=True)
    import_hash = models.CharField(max_length=64, db_index=True)
    raw_data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.DETECTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("payment_date", "title")

    def __str__(self):
        return f"{self.title} - {self.amount}"


class PaymentNotification(models.Model):
    class Kind(models.TextChoices):
        SCHEDULED_CONFIRMATION = "scheduled_confirmation", "Confirmação de agendamento"
        REMINDER_1_DAY = "reminder_1_day", "Lembrete de 1 dia"
        REMINDER_DUE_TODAY = "reminder_due_today", "Lembrete do dia"

    payment = models.ForeignKey(Payment, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=32, choices=Kind.choices)
    scheduled_date = models.DateField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)
        constraints = [
            models.UniqueConstraint(fields=["payment", "kind", "scheduled_date"], name="unique_payment_notification_per_date"),
        ]

    def __str__(self):
        return f"{self.payment} - {self.get_kind_display()} - {self.scheduled_date}"
