import re
import unicodedata

from .models import Payment


CREDIT_CARD_BILL_KEYWORDS = (
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


def guess_payment_kind(title="", category=None):
    category_name = getattr(category, "name", "") if category else ""
    normalized = normalize_text(f"{title} {category_name}")
    if any(keyword in normalized for keyword in CREDIT_CARD_BILL_KEYWORDS):
        return Payment.Kind.CREDIT_CARD_BILL
    return Payment.Kind.EXPENSE


def normalize_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()
