from django.db import migrations, models


def clear_cached_insights(apps, schema_editor):
    FinancialInsightSnapshot = apps.get_model("dashboard", "FinancialInsightSnapshot")
    FinancialInsightSnapshot.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0002_alter_financialinsightsnapshot_source"),
    ]

    operations = [
        migrations.RunPython(clear_cached_insights, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="financialinsightsnapshot",
            name="source",
            field=models.CharField(
                blank=True,
                choices=[("gemini", "Gemini"), ("local", "Análise local")],
                max_length=16,
            ),
        ),
    ]
