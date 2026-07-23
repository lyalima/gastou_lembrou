from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_legalacceptance"),
    ]

    operations = [
        migrations.AlterField(
            model_name="legalacceptance",
            name="source",
            field=models.CharField(
                choices=[
                    ("email", "Cadastro por email"),
                    ("google", "Cadastro com Google"),
                    ("update", "Atualização de termos"),
                ],
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="LegalUpdateNotification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("terms_version", models.CharField(max_length=20)),
                ("privacy_version", models.CharField(max_length=20)),
                ("notified_at", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="legal_update_notifications",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "ordering": ("-notified_at",),
            },
        ),
        migrations.AddConstraint(
            model_name="legalupdatenotification",
            constraint=models.UniqueConstraint(
                fields=("user", "terms_version", "privacy_version"),
                name="unique_legal_update_notification_per_version",
            ),
        ),
    ]
