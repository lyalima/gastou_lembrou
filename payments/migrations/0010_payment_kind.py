from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0009_category_user_payment_import_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="payment",
            name="kind",
            field=models.CharField(
                choices=[
                    ("expense", "Gasto comum"),
                    ("credit_card_bill", "Pagamento de fatura"),
                ],
                default="expense",
                max_length=32,
            ),
        ),
    ]
