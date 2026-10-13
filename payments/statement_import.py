import csv
import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

import pymupdf
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .classification import guess_payment_kind
from .models import Payment, PaymentMethod


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


PREVIEW_TTL_SECONDS = 1800
MAX_PREVIEW_ITEMS = 500


DATE_FORMATS = ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d")
DESCRIPTION_HEADERS = ("descricao", "historico", "lancamento", "titulo", "memo", "name", "description", "detalhes", "estabelecimento")
AMOUNT_HEADERS = ("valor", "amount", "trnamt", "montante", "valor r", "valor da transacao", "valor da operacao")
DEBIT_HEADERS = ("debito", "saida", "valor debito", "debit")
CREDIT_HEADERS = ("credito", "entrada", "valor credito", "credit")
DATE_HEADERS = ("data", "data lancamento", "dtposted", "date", "data da transacao", "data do movimento", "data da operacao")
TYPE_HEADERS = ("tipo", "tipo de transacao", "natureza", "type")
PDF_DATE = re.compile(r"^\s*(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b")
PDF_AMOUNT = re.compile(r"(?<!\d)(?:R\$\s*)?([+-]?(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2})(?:\s*([DC]))?(?!\d)", re.I)
PDF_DAY_HEADER = re.compile(r"^(\d{1,2}) de ([a-z]+) de (\d{4})\b.*\bsaldo do dia\b", re.I)
PDF_MONEY = r"-?\s*R\$\s*-?\s*(?:\d{1,3}(?:\.\d{3})*|\d+),\d{2}"
PDF_BALANCE_ROW = re.compile(rf"^(.+?)\s+({PDF_MONEY})\s+({PDF_MONEY})\s*$", re.I)
PORTUGUESE_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def extract_statement_transactions(statement_file):
    content = statement_file.read()
    statement_file.seek(0)
    suffix = statement_file.name.lower().rsplit(".", 1)[-1]
    if suffix == "pdf":
        return parse_pdf(content)
    text = _decode_content(content)
    return parse_ofx(text) if suffix == "ofx" else parse_csv(text)


def prepare_statement_preview(user, statement_file):
    transactions = extract_statement_transactions(statement_file)
    expenses = [item for item in transactions if item.amount > 0]
    if len(expenses) > MAX_PREVIEW_ITEMS:
        raise ValueError("O extrato contém mais de 500 saídas. Importe um período menor.")
    rows = [
        {
            "id": index,
            "hash": build_import_hash(user.pk, item),
            "title": item.title[:200],
            "amount": str(item.amount),
            "payment_date": item.payment_date.isoformat(),
            "display_date": item.payment_date.strftime("%d/%m/%Y"),
        }
        for index, item in enumerate(expenses)
    ]
    existing = set(Payment.objects.filter(user=user, import_hash__in=[row["hash"] for row in rows]).values_list("import_hash", flat=True))
    seen = set()
    available = []
    for row in rows:
        if row["hash"] in existing or row["hash"] in seen:
            continue
        seen.add(row["hash"])
        available.append(row)
    token = str(uuid.uuid4())
    preview = {"rows": available, "ignored_income": len(transactions) - len(expenses), "skipped": len(rows) - len(available)}
    cache.set(_preview_cache_key(user.pk, token), preview, timeout=PREVIEW_TTL_SECONDS)
    return token, preview


def get_statement_preview(user, token):
    try:
        token = str(uuid.UUID(token))
    except (ValueError, TypeError, AttributeError):
        return None
    return cache.get(_preview_cache_key(user.pk, token))


def confirm_statement_preview(user, token, selected_ids):
    preview = get_statement_preview(user, token)
    if preview is None:
        raise ValueError("A prévia expirou. Envie o extrato novamente.")
    selected = set(selected_ids)
    allowed = {str(row["id"]) for row in preview["rows"]}
    if not selected or not selected.issubset(allowed):
        raise ValueError("Selecione pelo menos um lançamento válido para importar.")

    created_count = skipped_count = 0
    with transaction.atomic():
        method = PaymentMethod.objects.filter(name__iexact="Pix").first()
        if method is None:
            method = PaymentMethod.objects.create(name="Pix")
        for row in preview["rows"]:
            if str(row["id"]) not in selected:
                continue
            _, created = Payment.objects.get_or_create(
                user=user,
                import_hash=row["hash"],
                defaults={
                    "title": row["title"],
                    "description": "Importado de extrato bancário.",
                    "kind": guess_payment_kind(row["title"]),
                    "amount": Decimal(row["amount"]),
                    "payment_date": date.fromisoformat(row["payment_date"]),
                    "payment_method": method,
                    "imported_at": timezone.now(),
                },
            )
            created_count += int(created)
            skipped_count += int(not created)
    cache.delete(_preview_cache_key(user.pk, token))
    return ImportResult(created_count, skipped_count, preview["ignored_income"], [])


def _preview_cache_key(user_id, token):
    return f"payments:statement-preview:{user_id}:{token}"


def parse_pdf(content):
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except (pymupdf.FileDataError, pymupdf.EmptyFileError) as exc:
        raise ValueError("Não foi possível abrir este PDF. Exporte novamente o extrato pelo banco.") from exc

    transactions = []
    try:
        if len(document) > 50:
            raise ValueError("O PDF tem páginas demais para importar de uma só vez.")
        has_text = False
        for page_number, page in enumerate(document):
            text = page.get_text("text", sort=True)
            has_text = has_text or bool(text.strip())
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            day_date = None
            for index, line in enumerate(lines):
                day_header = PDF_DAY_HEADER.match(_normalize(line))
                if day_header:
                    month = PORTUGUESE_MONTHS.get(day_header.group(2))
                    try:
                        day_date = date(int(day_header.group(3)), month, int(day_header.group(1))) if month else None
                    except ValueError:
                        day_date = None
                    continue
                if day_date:
                    balance_row = PDF_BALANCE_ROW.match(line)
                    if balance_row:
                        title = _clean_title(balance_row.group(1))
                        transaction_amount = parse_amount(balance_row.group(2))
                        if _normalize(title).startswith("pix enviado") and transaction_amount is not None and transaction_amount < 0:
                            transactions.append(StatementTransaction(title, abs(transaction_amount), day_date, f"pdf:{page_number}:{line}"))
                        continue
                date_match = PDF_DATE.match(line)
                if not date_match:
                    continue
                date_value = parse_date(date_match.group(1))
                if not date_value:
                    continue
                remainder = line[date_match.end():].strip(" -|\t")
                if not remainder and index + 2 < len(lines):
                    remainder = f"{lines[index + 1]} {lines[index + 2]}"
                elif remainder and not PDF_AMOUNT.search(remainder) and index + 1 < len(lines):
                    remainder = f"{remainder} {lines[index + 1]}"
                amount_match = PDF_AMOUNT.search(remainder)
                if not amount_match:
                    continue
                title = _clean_title(remainder[:amount_match.start()].strip(" -|\t"))
                if not title or re.search(r"\b(saldo|total|limite)\b", title, re.I):
                    continue
                amount = parse_amount(amount_match.group(1))
                if amount is None:
                    continue
                if amount_match.group(2) and amount_match.group(2).upper() == "D":
                    amount = abs(amount)
                elif amount_match.group(2) and amount_match.group(2).upper() == "C":
                    amount = -abs(amount)
                else:
                    amount = -amount
                transactions.append(StatementTransaction(title, amount, date_value, f"pdf:{page_number}:{line}"))
        if not has_text:
            raise ValueError("Este PDF não contém texto selecionável. Exporte o extrato em PDF digital, CSV ou OFX.")
    finally:
        document.close()
    return transactions


def parse_csv(text):
    lines = text.splitlines()
    header_index = None
    delimiter = None
    for index, line in enumerate(lines[:30]):
        for candidate in (";", ",", "\t", "|"):
            columns = next(csv.reader([line], delimiter=candidate))
            names = {_normalize(column) for column in columns}
            if (
                len(columns) >= 3
                and names.intersection(DATE_HEADERS)
                and names.intersection(DESCRIPTION_HEADERS)
                and names.intersection((*AMOUNT_HEADERS, *DEBIT_HEADERS, *CREDIT_HEADERS))
            ):
                header_index = index
                delimiter = candidate
                break
        if header_index is not None:
            break
    if header_index is None:
        return []

    reader = csv.DictReader(StringIO("\n".join(lines[header_index:])), delimiter=delimiter)
    if not reader.fieldnames:
        return []

    normalized_headers = {_normalize(header): header for header in reader.fieldnames if header}
    pix_only = {"data lancamento", "historico", "descricao", "valor", "saldo"}.issubset(normalized_headers)
    transactions = []

    for row in reader:
        if pix_only and not _normalize(_first_value(row, normalized_headers, ("historico",))).startswith("pix enviado"):
            continue
        title = _first_value(row, normalized_headers, DESCRIPTION_HEADERS)
        raw_date = _first_value(row, normalized_headers, DATE_HEADERS)
        raw_amount = _first_value(row, normalized_headers, AMOUNT_HEADERS)
        debit_amount = _first_value(row, normalized_headers, DEBIT_HEADERS)
        credit_amount = _first_value(row, normalized_headers, CREDIT_HEADERS)
        transaction_type = _normalize(_first_value(row, normalized_headers, TYPE_HEADERS))

        if not title or not raw_date:
            continue

        date_value = parse_date(raw_date)
        parsed_amount = parse_amount(raw_amount) if raw_amount else None
        amount = abs(parsed_amount) if parsed_amount and parsed_amount < 0 else (-(parsed_amount or Decimal("0")) if parsed_amount else None)

        if debit_amount:
            amount = abs(parse_amount(debit_amount) or Decimal("0"))
        elif credit_amount and not raw_amount:
            amount = -(abs(parse_amount(credit_amount) or Decimal("0")))
        elif parsed_amount is not None and transaction_type in {"debito", "saida", "debit", "payment", "pagamento"}:
            amount = abs(parsed_amount)
        elif parsed_amount is not None and transaction_type in {"credito", "entrada", "credit", "deposito"}:
            amount = -abs(parsed_amount)

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
