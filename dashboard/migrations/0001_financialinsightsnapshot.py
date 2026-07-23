from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="FinancialInsightSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_key", models.CharField(max_length=7)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Processando"), ("ready", "Pronto"), ("error", "Erro")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("source", models.CharField(blank=True, choices=[("openai", "OpenAI"), ("local", "Analise local")], max_length=16)),
                ("insights", models.JSONField(blank=True, default=list)),
                ("summary", models.CharField(blank=True, max_length=240)),
                ("error_message", models.CharField(blank=True, max_length=240)),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="financial_insights",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("-updated_at",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "period_key"),
                        name="unique_financial_insight_snapshot_period",
                    ),
                ],
            },
        ),
    ]
