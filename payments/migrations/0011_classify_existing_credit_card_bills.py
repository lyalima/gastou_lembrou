from django.db import migrations


KEYWORDS = (
    "fatura cartao",
    "fatura do cartao",
    "fatura de cartao",
    "fatura de cartao de credito",
    "fatura cartao de credito",
    "pagamento fatura",
    "pagamento de fatura",
    "pag fatura",
    "cartao credito",
    "cartao de credito",
    "credcard",
)


def normalize_text(value):
    import re
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()


def classify_existing_credit_card_bills(apps, schema_editor):
    Payment = apps.get_model("payments", "Payment")

    queryset = Payment.objects.select_related("category").filter(kind="expense")
    ids_to_update = []
    for payment in queryset.iterator():
        category_name = payment.category.name if payment.category_id else ""
        searchable = normalize_text(f"{payment.title} {category_name}")
        if any(keyword in searchable for keyword in KEYWORDS):
            ids_to_update.append(payment.pk)

    if ids_to_update:
        Payment.objects.filter(pk__in=ids_to_update).update(kind="credit_card_bill")


class Migration(migrations.Migration):
    dependencies = [
        ("payments", "0010_payment_kind"),
    ]

    operations = [
        migrations.RunPython(classify_existing_credit_card_bills, migrations.RunPython.noop),
    ]
