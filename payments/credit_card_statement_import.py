import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import fitz
import requests
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from core.gemini import generate_content

from .categorization import local_category_match
from .classification import normalize_text
from .models import Category, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod
from .statement_import import parse_amount


MIN_EXTRACTED_TEXT_LENGTH = 300


@dataclass(frozen=True)
class CardStatementEntry:
    title: str
    amount: Decimal
    payment_date: date
    raw_data: dict


def process_credit_card_statement(statement):
    extracted_text = extract_pdf_text(statement.file.path)
    statement.extracted_text = extracted_text
    statement.parser_source = CreditCardStatement.ParserSource.TEXT

    if len(normalize_text(extracted_text)) < MIN_EXTRACTED_TEXT_LENGTH:
        statement.status = CreditCardStatement.Status.FAILED
        statement.error_message = (
            "Não foi possível extrair texto suficiente do PDF. "
            "Esse arquivo parece ser imagem/scaneado ou possui um layout ainda não suportado."
        )
        statement.save(update_fields=["extracted_text", "parser_source", "status", "error_message", "updated_at"])
        return []

    entries, source = parse_credit_card_entries(extracted_text)
    statement.parser_source = source

    if not entries:
        statement.status = CreditCardStatement.Status.FAILED
        statement.error_message = (
            "O texto foi extraído, mas nenhum lançamento de cartão foi identificado com segurança."
        )
        statement.save(update_fields=["extracted_text", "parser_source", "status", "error_message", "updated_at"])
        return []

    categories = list(Category.objects.filter(Q(user__isnull=True) | Q(user=statement.user)))
    created_items = []
    for entry in entries:
        item, created = CreditCardStatementItem.objects.get_or_create(
            statement=statement,
            import_hash=build_credit_card_import_hash(statement.user_id, entry),
            defaults={
                "title": entry.title[:200],
                "amount": entry.amount,
                "payment_date": entry.payment_date,
                "category": local_category_match(entry.title, categories),
                "raw_data": entry.raw_data,
            },
        )
        if created:
            created_items.append(item)

    statement.status = CreditCardStatement.Status.READY
    statement.error_message = ""
    statement.save(update_fields=["extracted_text", "parser_source", "status", "error_message", "updated_at"])
    return created_items or list(statement.items.all())


def extract_pdf_text(path):
    document = fitz.open(path)
    try:
        return "\n".join(page.get_text("text") for page in document)
    finally:
        document.close()


def parse_credit_card_entries(text):
    if settings.GEMINI_API_KEY:
        try:
            entries = parse_entries_with_gemini(text)
            if entries:
                return entries, CreditCardStatement.ParserSource.GEMINI
        except (requests.RequestException, ValueError, KeyError, TypeError, json.JSONDecodeError):
            pass

    return parse_entries_locally(text), CreditCardStatement.ParserSource.REGEX


def parse_entries_with_gemini(text):
    schema = {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Data no formato YYYY-MM-DD."},
                        "title": {"type": "string", "description": "Descrição do estabelecimento ou lançamento."},
                        "amount": {"type": "number", "description": "Valor positivo da compra em reais."},
                    },
                    "required": ["date", "title", "amount"],
                },
            }
        },
        "required": ["entries"],
    }
    payload = generate_content(
        {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Extraia somente compras, assinaturas, tarifas ou lançamentos de uma fatura de cartão de crédito. "
                            "Não inclua pagamento da fatura, saldo anterior, total da fatura, limite, juros futuros, dados cadastrais "
                            "ou linhas de cabeçalho. Retorne datas no formato YYYY-MM-DD e valores positivos em reais."
                        )
                    }
                ]
            },
            "contents": [{"role": "user", "parts": [{"text": text[:45000]}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        },
    )
    parts = payload["candidates"][0]["content"]["parts"]
    output_text = next(part["text"] for part in parts if part.get("text"))
    data = json.loads(output_text)
    entries = []
    for item in data.get("entries", []):
        parsed_date = parse_card_date(item.get("date"))
        amount = parse_amount(str(item.get("amount", "")))
        title = clean_entry_title(item.get("title"))
        if parsed_date and amount and amount > 0 and title and is_probable_purchase(title):
            entries.append(CardStatementEntry(title=title, amount=amount, payment_date=parsed_date, raw_data=item))
    return entries


def parse_entries_locally(text):
    entries = []
    current_year = timezone.localdate().year
    line_pattern = re.compile(
        r"(?P<date>\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b)\s+"
        r"(?P<title>.+?)\s+"
        r"(?:R\$\s*)?(?P<amount>-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})\b"
    )

    for line in text.splitlines():
        normalized_line = " ".join(line.split())
        match = line_pattern.search(normalized_line)
        if not match:
            continue
        parsed_date = parse_card_date(match.group("date"), default_year=current_year)
        amount = parse_amount(match.group("amount"))
        title = clean_entry_title(match.group("title"))
        if parsed_date and amount and amount > 0 and title and is_probable_purchase(title):
            entries.append(
                CardStatementEntry(
                    title=title,
                    amount=amount,
                    payment_date=parsed_date,
                    raw_data={"line": normalized_line},
                )
            )
    return entries


def parse_card_date(value, default_year=None):
    value = str(value or "").strip()
    default_year = default_year or timezone.localdate().year
    for date_format in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y"):
        try:
            parsed = datetime.strptime(value, date_format).date()
            if parsed.year < 2000:
                parsed = date(default_year, parsed.month, parsed.day)
            return parsed
        except ValueError:
            continue
    short_match = re.match(r"^(\d{1,2})[/-](\d{1,2})$", value)
    if short_match:
        day, month = [int(part) for part in short_match.groups()]
        try:
            return date(default_year, month, day)
        except ValueError:
            return None
    return None


def clean_entry_title(value):
    title = re.sub(r"\s+", " ", str(value or "")).strip(" -")
    return title[:200]


def is_probable_purchase(title):
    normalized = normalize_text(title)
    blocked_terms = {
        "pagamento",
        "pagamento recebido",
        "pagamento de fatura",
        "total",
        "total da fatura",
        "saldo anterior",
        "limite",
        "vencimento",
        "encargos",
        "juros",
    }
    return bool(normalized) and not any(term in normalized for term in blocked_terms)


def build_credit_card_import_hash(user_id, entry):
    base = f"credit-card-statement|{user_id}|{entry.payment_date.isoformat()}|{entry.amount}|{normalize_text(entry.title)}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def get_or_create_credit_card_method():
    for method in PaymentMethod.objects.all():
        if normalize_text(method.name) in {"cartao de credito", "credito", "cartao credito"}:
            return method
    return PaymentMethod.objects.create(name="Cartão de crédito")


def payment_duplicate_exists(user, title, amount, payment_date, payment_method, import_hash):
    return Payment.objects.filter(user=user).filter(
        Q(import_hash=import_hash)
        | Q(
            title__iexact=title,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            kind=Payment.Kind.EXPENSE,
        )
    ).exists()
