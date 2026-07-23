import csv
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from django.utils import timezone

from .classification import guess_payment_kind
from .models import Payment


@dataclass(frozen=True)
class StatementTransaction:
    title: str
    amount: Decimal
    payment_date: date
    raw_identifier: str = ""


@dataclass(frozen=True)
class ImportResult:
    created: int
    skipped: int
    ignored_income: int
    errors: list[str]


DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d")
DESCRIPTION_HEADERS = ("descricao", "historico", "lancamento", "titulo", "memo", "name", "description")
AMOUNT_HEADERS = ("valor", "amount", "trnamt", "montante")
DEBIT_HEADERS = ("debito", "saida", "valor debito", "debit")
CREDIT_HEADERS = ("credito", "entrada", "valor credito", "credit")
DATE_HEADERS = ("data", "data lancamento", "dtposted", "date")
def import_statement_payments(user, statement_file):
    content = statement_file.read()
    statement_file.seek(0)
    suffix = statement_file.name.lower().rsplit(".", 1)[-1]
    text = _decode_content(content)
    transactions = parse_ofx(text) if suffix == "ofx" else parse_csv(text)

    created = 0
    skipped = 0
    ignored_income = 0
    errors = []

    for transaction in transactions:
        if transaction.amount <= 0:
            ignored_income += 1
            continue

        import_hash = build_import_hash(user.pk, transaction)
        if Payment.objects.filter(user=user, import_hash=import_hash).exists():
            skipped += 1
            continue

        try:
            Payment.objects.create(
                user=user,
                title=transaction.title[:200],
                description="Importado de extrato bancário.",
                kind=guess_payment_kind(transaction.title),
                amount=transaction.amount,
                payment_date=transaction.payment_date,
                import_hash=import_hash,
                imported_at=timezone.now(),
            )
            created += 1
        except Exception as exc:
            errors.append(f"{transaction.title}: {exc}")

    return ImportResult(created=created, skipped=skipped, ignored_income=ignored_income, errors=errors)


def parse_csv(text):
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;|\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"

    reader = csv.DictReader(StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return []

    normalized_headers = {_normalize(header): header for header in reader.fieldnames if header}
    transactions = []

    for row in reader:
        title = _first_value(row, normalized_headers, DESCRIPTION_HEADERS)
        raw_date = _first_value(row, normalized_headers, DATE_HEADERS)
        raw_amount = _first_value(row, normalized_headers, AMOUNT_HEADERS)
        debit_amount = _first_value(row, normalized_headers, DEBIT_HEADERS)
        credit_amount = _first_value(row, normalized_headers, CREDIT_HEADERS)

        if not title or not raw_date:
            continue

        date_value = parse_date(raw_date)
        parsed_amount = parse_amount(raw_amount) if raw_amount else None
        amount = abs(parsed_amount) if parsed_amount and parsed_amount < 0 else (-(parsed_amount or Decimal("0")) if parsed_amount else None)

        if debit_amount:
            amount = abs(parse_amount(debit_amount) or Decimal("0"))
        elif credit_amount and not raw_amount:
            amount = -(abs(parse_amount(credit_amount) or Decimal("0")))

        if not date_value or amount is None:
            continue

        transactions.append(
            StatementTransaction(
                title=_clean_title(title),
                amount=amount,
                payment_date=date_value,
                raw_identifier="|".join(str(row.get(header, "")) for header in reader.fieldnames),
            )
        )

    return transactions


def parse_ofx(text):
    transactions = []
    for block in re.findall(r"<STMTTRN>(.*?)(?=<STMTTRN>|</BANKTRANLIST>|</CREDITCARDMSGSRSV1>)", text, re.I | re.S):
        raw_amount = _ofx_tag(block, "TRNAMT")
        raw_date = _ofx_tag(block, "DTPOSTED")
        title = _ofx_tag(block, "MEMO") or _ofx_tag(block, "NAME") or "Transação importada"
        fitid = _ofx_tag(block, "FITID")
        trn_type = (_ofx_tag(block, "TRNTYPE") or "").casefold()
        amount = parse_amount(raw_amount)
        date_value = parse_date((raw_date or "")[:8])

        if amount is None or not date_value:
            continue
        if amount > 0 and trn_type not in {"debit", "payment", "pos", "atm", "check", "fee"}:
            transactions.append(StatementTransaction(_clean_title(title), -amount, date_value, fitid))
            continue

        transactions.append(StatementTransaction(_clean_title(title), abs(amount), date_value, fitid))
    return transactions


def build_import_hash(user_id, transaction):
    base = f"{user_id}|{transaction.payment_date.isoformat()}|{transaction.amount}|{transaction.title}|{transaction.raw_identifier}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def parse_date(value):
    value = str(value or "").strip()
    value = re.sub(r"[^0-9/\-]", "", value)
    for date_format in DATE_FORMATS:
        try:
            return datetime.strptime(value[:10] if date_format != "%Y%m%d" else value[:8], date_format).date()
        except ValueError:
            continue
    return None


def parse_amount(value):
    if value is None:
        return None
    normalized = str(value).strip()
    if not normalized:
        return None
    normalized = normalized.replace("R$", "").replace(" ", "")
    if "," in normalized:
        normalized = normalized.replace(".", "").replace(",", ".")
    normalized = re.sub(r"[^0-9.\-]", "", normalized)
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _decode_content(content):
    for encoding in ("utf-8-sig", "latin-1", "cp1252"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="ignore")


def _first_value(row, normalized_headers, candidates):
    for candidate in candidates:
        header = normalized_headers.get(candidate)
        if header and row.get(header):
            return row.get(header)
    return ""


def _ofx_tag(block, tag):
    match = re.search(rf"<{tag}>([^<\r\n]+)", block, re.I)
    return match.group(1).strip() if match else ""


def _clean_title(value):
    return re.sub(r"\s+", " ", str(value or "Transação importada")).strip() or "Transação importada"


def _normalize(value):
    from .classification import normalize_text

    return normalize_text(value)
