from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0007_alter_paymentnotification_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="category",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payments",
                to="payments.category",
            ),
        ),
    ]
