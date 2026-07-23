from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0012_credit_card_statement_import"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="is_installment",
            field=models.BooleanField(default=False),
        ),
    ]
