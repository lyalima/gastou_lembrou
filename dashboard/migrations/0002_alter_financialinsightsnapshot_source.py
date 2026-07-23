from django.db import migrations, models


def remove_openai_snapshots(apps, schema_editor):
    FinancialInsightSnapshot = apps.get_model("dashboard", "FinancialInsightSnapshot")
    FinancialInsightSnapshot.objects.filter(source="openai").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("dashboard", "0001_financialinsightsnapshot"),
    ]

    operations = [
        migrations.RunPython(remove_openai_snapshots, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="financialinsightsnapshot",
            name="source",
            field=models.CharField(
                blank=True,
                choices=[("gemini", "Gemini"), ("local", "Analise local")],
                max_length=16,
            ),
        ),
    ]
