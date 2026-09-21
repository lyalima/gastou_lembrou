import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("payments", "0014_payment_installment_group_payment_installment_number_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AssistantMessage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(choices=[("user", "Usuário"), ("assistant", "Spike")], max_length=16)),
                ("content", models.TextField(max_length=2000)),
                ("intent", models.CharField(blank=True, max_length=64)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="assistant_messages", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("created_at",)},
        ),
        migrations.CreateModel(
            name="GoogleCalendarConnection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("google_email", models.EmailField(blank=True, max_length=254)),
                ("access_token_encrypted", models.TextField(blank=True)),
                ("refresh_token_encrypted", models.TextField(blank=True)),
                ("token_expires_at", models.DateTimeField(blank=True, null=True)),
                ("scope", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="google_calendar_connection", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "verbose_name": "Conexão com Google Agenda",
                "verbose_name_plural": "Conexões com Google Agenda",
            },
        ),
        migrations.CreateModel(
            name="PaymentCalendarEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("google_event_id", models.CharField(blank=True, max_length=255)),
                ("calendar_id", models.CharField(default="primary", max_length=255)),
                ("title", models.CharField(max_length=200)),
                ("scheduled_for", models.DateField()),
                ("status", models.CharField(choices=[("created", "Criado"), ("failed", "Falhou"), ("deleted", "Excluído")], default="created", max_length=16)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("payment", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="calendar_event", to="payments.payment")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="payment_calendar_events", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="paymentcalendarevent",
            constraint=models.UniqueConstraint(fields=("user", "payment"), name="unique_calendar_event_per_user_payment"),
        ),
    ]

