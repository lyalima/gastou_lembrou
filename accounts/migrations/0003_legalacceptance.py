from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0002_alter_user_telefone"),
    ]

    operations = [
        migrations.CreateModel(
            name="LegalAcceptance",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("terms_version", models.CharField(max_length=20)),
                ("privacy_version", models.CharField(max_length=20)),
                (
                    "source",
                    models.CharField(
                        choices=[("email", "Cadastro por email"), ("google", "Cadastro com Google")],
                        max_length=16,
                    ),
                ),
                ("accepted_at", models.DateTimeField(auto_now_add=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=500)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="legal_acceptances",
                        to="accounts.user",
                    ),
                ),
            ],
            options={
                "ordering": ("-accepted_at",),
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "terms_version", "privacy_version"),
                        name="unique_legal_acceptance_per_version",
                    )
                ],
            },
        ),
    ]
