import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0011_classify_existing_credit_card_bills"),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditCardStatement",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="payments/credit_card_statements/")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("processing", "Processando"),
                            ("ready", "Pronto para revisão"),
                            ("confirmed", "Importado"),
                            ("failed", "Falha"),
                        ],
                        default="processing",
                        max_length=24,
                    ),
                ),
                (
                    "parser_source",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("text", "Texto do PDF"),
                            ("gemini", "Gemini"),
                            ("regex", "Leitura local"),
                        ],
                        max_length=24,
                    ),
                ),
                ("extracted_text", models.TextField(blank=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="credit_card_statements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddField(
            model_name="payment",
            name="credit_card_statement",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="payments",
                to="payments.creditcardstatement",
            ),
        ),
        migrations.CreateModel(
            name="CreditCardStatementItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=20)),
                ("payment_date", models.DateField()),
                ("import_hash", models.CharField(db_index=True, max_length=64)),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("detected", "Detectado"),
                            ("imported", "Importado"),
                            ("skipped", "Ignorado"),
                        ],
                        default="detected",
                        max_length=24,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="credit_card_statement_items",
                        to="payments.category",
                    ),
                ),
                (
                    "payment",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="statement_item",
                        to="payments.payment",
                    ),
                ),
                (
                    "statement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="payments.creditcardstatement",
                    ),
                ),
            ],
            options={
                "ordering": ("payment_date", "title"),
            },
        ),
    ]
