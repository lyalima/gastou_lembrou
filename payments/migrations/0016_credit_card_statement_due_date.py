import re
from datetime import datetime

from django.db import migrations, models


DUE_DATE_PATTERN = re.compile(
    r"\bdata\s+de\s+vencimento\b[^\d]{0,120}(\d{1,2}/\d{1,2}/\d{4})\b",
    re.IGNORECASE,
)
INSTALLMENT_PATTERN = re.compile(r"\bparcela\s*(\d{1,2})\s*de\s*(\d{1,2})\b", re.IGNORECASE)


def backfill_statement_due_dates(apps, schema_editor):
    Statement = apps.get_model("payments", "CreditCardStatement")
    Item = apps.get_model("payments", "CreditCardStatementItem")
    Payment = apps.get_model("payments", "Payment")
    alias = schema_editor.connection.alias

    for statement in Statement.objects.using(alias).exclude(extracted_text="").iterator():
        match = DUE_DATE_PATTERN.search(statement.extracted_text)
        if not match:
            continue
        try:
            due_date = datetime.strptime(match.group(1), "%d/%m/%Y").date()
        except ValueError:
            continue

        Statement.objects.using(alias).filter(pk=statement.pk).update(due_date=due_date)
        Payment.objects.using(alias).filter(credit_card_statement_id=statement.pk).update(statement_due_date=due_date)

        for item in Item.objects.using(alias).filter(statement_id=statement.pk, payment_id__isnull=False).values("payment_id", "title"):
            installment = INSTALLMENT_PATTERN.search(item["title"])
            if not installment:
                continue
            number, total = map(int, installment.groups())
            if 1 <= number <= total:
                Payment.objects.using(alias).filter(pk=item["payment_id"]).update(
                    is_installment=True,
                    installment_number=number,
                    installment_total=total,
                )


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0015_payment_recurrence_number_payment_statement_due_date_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="creditcardstatement",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_statement_due_dates, migrations.RunPython.noop),
    ]
