from decimal import Decimal
import pymupdf
from django.conf import settings
from django.utils import timezone
from payments.classification import normalize_text

from .metrics import get_dashboard_metrics


PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN = 46
GREEN = (0.051, 0.42, 0.353)
TEXT = (0.059, 0.09, 0.165)
MUTED = (0.298, 0.353, 0.424)
LIGHT = (0.969, 0.98, 0.973)
BORDER = (0.812, 0.914, 0.871)


def build_dashboard_report_pdf(user, month):
    metrics = get_dashboard_metrics(user, month=month)
    builder = DashboardPdfBuilder(user, metrics, month)
    builder.build()
    return builder.document.tobytes(garbage=4, deflate=True)


class DashboardPdfBuilder:
    def __init__(self, user, metrics, month):
        self.user = user
        self.metrics = metrics
        self.month = month
        self.document = pymupdf.open()
        self.page = None
        self.y = MARGIN

    def build(self):
        self.add_page()
        self.header()
        self.summary()
        self.metric_table("Gastos por categoria", self.metrics["category_metrics"], ("Categoria", "Qtd.", "Total"))
        self.metric_table("Evolução mensal", self.metrics["month_metrics"], ("Data", "Pagamentos", "Total"))
        self.metric_table(
            "Gastos por forma de pagamento",
            self.metrics["payment_method_metrics"],
            ("Forma de pagamento", "Qtd.", "Total"),
        )
        self.registered_payments()
        self.footer()

    def add_page(self):
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.page.draw_rect(pymupdf.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), color=LIGHT, fill=LIGHT)
        self.y = MARGIN

    def ensure_space(self, height):
        if self.y + height <= PAGE_HEIGHT - MARGIN:
            return
        self.footer()
        self.add_page()

    def header(self):
        logo_path = settings.BASE_DIR / "static" / "img" / "gastou-lembrou-logo.png"
        if logo_path.exists():
            self.page.insert_image(pymupdf.Rect(MARGIN, self.y, MARGIN + 42, self.y + 42), filename=str(logo_path))
            title_x = MARGIN + 54
        else:
            title_x = MARGIN
        self.text("Gastou, Lembrou!", title_x, self.y + 8, size=18, color=GREEN, bold=True)
        self.text(f"Relatorio mensal - {self.month.strftime('%m/%Y')}", title_x, self.y + 30, size=10, color=MUTED)
        self.text(
            f"Gerado em {timezone.localtime().strftime('%d/%m/%Y %H:%M')} para {self.user.email}",
            MARGIN,
            self.y + 64,
            size=9,
            color=MUTED,
        )
        self.y += 100

    def summary(self):
        card_width = (PAGE_WIDTH - (2 * MARGIN) - 20) / 3
        cards = [
            ("Total registrado", format_currency(self.metrics["total"])),
            ("Total de Pagamentos", str(self.metrics["payment_count"])),
            ("Pagamentos agendados", str(self.metrics["scheduled_count"])),
        ]
        for index, (label, value) in enumerate(cards):
            x = MARGIN + index * (card_width + 10)
            rect = pymupdf.Rect(x, self.y, x + card_width, self.y + 72)
            self.page.draw_rect(rect, color=BORDER, fill=(1, 1, 1), width=0.8)
            self.text(label, x + 12, self.y + 18, size=9, color=MUTED)
            self.text(value, x + 12, self.y + 46, size=16, color=GREEN, bold=True)
        self.y += 100

    def metric_table(self, title, rows, headers):
        self.ensure_space(90)
        self.section_title(title)
        if not rows:
            self.empty_state("Nenhum dado registrado.")
            return
        self.table_header(headers)
        for row in rows:
            values = (row["name"], str(row["count"]), format_currency(row["total"]))
            lines = [self.wrap_text(str(value), width) for value, width in zip(values, (288, 68, 103))]
            height = max(len(part) for part in lines) * 12 + 14
            if self.y + height > PAGE_HEIGHT - MARGIN:
                self.ensure_space(height)
                self.section_title(title + " (continuação)")
                self.table_header(headers)
            self.table_row(values, height=height)
        self.y += 12

    def registered_payments(self):
        payments = list(self.metrics["report_payments"])
        self.ensure_space(110)
        self.section_title("Pagamentos registrados")
        if not payments:
            self.empty_state("Nenhum pagamento registrado.")
            return
        groups = {"Cartão de crédito": [], "Gastos agendados": [], "Outras formas de pagamento": []}
        for payment in payments:
            method = normalize_text(getattr(payment.payment_method, "name", ""))
            group = "Gastos agendados" if payment.scheduled_date else (
                "Cartão de crédito" if payment.credit_card_id or method in {"cartao de credito", "cartao credito", "credito"} else "Outras formas de pagamento"
            )
            groups[group].append(payment)
        for group, entries in groups.items():
            if not entries:
                continue
            self.ensure_space(130)
            self.section_title(group)
            for payment in entries:
                method = getattr(payment.payment_method, "name", "Não informada")
                details = [payment.title, f"Categoria: {payment.category.name if payment.category_id else 'Sem categoria'}"]
                if payment.scheduled_date:
                    details.extend([f"Data prevista: {payment.scheduled_date:%d/%m/%Y} - Agendado", f"Forma de pagamento: {method}"])
                elif group == "Cartão de crédito":
                    details.extend([f"Cartão: {payment.credit_card.name if payment.credit_card_id else 'Não informado'}", f"Data da compra: {self.date_label(payment.payment_date)}"])
                else:
                    details.extend([f"Forma de pagamento: {method}", f"Data de pagamento: {self.date_label(payment.payment_date)}"])
                if payment.credit_card_id or group == "Cartão de crédito":
                    if payment.scheduled_date:
                        details.append(f"Cartão: {payment.credit_card.name if payment.credit_card_id else 'Não informado'}")
                        details.append(f"Data da compra: {self.date_label(payment.payment_date)}")
                    details.append(f"Vencimento da fatura: {self.date_label(payment.statement_due_date)}")
                amount_label = format_currency(payment.amount)
                if payment.has_installment_info:
                    amount_label += f" - {payment.installment_number}/{payment.installment_total}"
                lines = [line for detail in details for line in self.wrap_text(detail, 335)]
                amount_lines = self.wrap_text(amount_label, 145)
                height = max(len(lines), len(amount_lines)) * 13 + 22
                if self.y + height > PAGE_HEIGHT - MARGIN:
                    self.ensure_space(height)
                    self.section_title(group + " (continuação)")
                for index, line in enumerate(lines):
                    self.text(line, MARGIN + 8, self.y + index * 13, size=8.5, color=TEXT if index == 0 else MUTED)
                for index, line in enumerate(amount_lines):
                    self.text(line, MARGIN + 350, self.y + index * 13, size=8.5, color=TEXT)
                self.y += height
                self.page.draw_line((MARGIN, self.y - 12), (PAGE_WIDTH - MARGIN, self.y - 12), color=BORDER, width=0.6)
            self.y += 12

    @staticmethod
    def date_label(value):
        return value.strftime("%d/%m/%Y") if value else "Não informada"

    @staticmethod
    def wrap_text(value, width, size=8.5):
        lines, current = [], ""
        for word in str(value).split():
            candidate = f"{current} {word}".strip()
            if pymupdf.get_text_length(candidate, fontname="helv", fontsize=size) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
            current = ""
            for char in word:
                if pymupdf.get_text_length(current + char, fontname="helv", fontsize=size) > width:
                    lines.append(current)
                    current = ""
                current += char
        return lines + ([current] if current else []) or ["-"]

    def section_title(self, title):
        self.text(title, MARGIN, self.y, size=14, color=TEXT, bold=True)
        self.y += 24

    def table_header(self, values):
        self.page.draw_rect(pymupdf.Rect(MARGIN, self.y - 14, PAGE_WIDTH - MARGIN, self.y + 8), color=GREEN, fill=GREEN)
        positions = self.column_positions(len(values))
        for x, value in zip(positions, values):
            self.text(value, x, self.y, size=8.5, color=(1, 1, 1), bold=True)
        self.y += 24

    def table_row(self, values, height=24):
        self.ensure_space(height + 18)
        self.page.draw_line((MARGIN, self.y - 12), (PAGE_WIDTH - MARGIN, self.y - 12), color=BORDER, width=0.6)
        positions = self.column_positions(len(values))
        for index, (x, value) in enumerate(zip(positions, values)):
            width = (positions[index + 1] if index + 1 < len(positions) else PAGE_WIDTH - MARGIN) - x - 8
            for line_number, line in enumerate(self.wrap_text(value, width)):
                self.text(line, x, self.y + line_number * 12, size=8.5, color=TEXT)
        self.y += height

    def empty_state(self, message):
        self.text(message, MARGIN, self.y, size=9, color=MUTED)
        self.y += 34

    def column_positions(self, count):
        if count == 4:
            return (MARGIN + 10, MARGIN + 205, MARGIN + 320, MARGIN + 425)
        return (MARGIN + 10, MARGIN + 310, MARGIN + 390)

    def text(self, value, x, y, size=10, color=TEXT, bold=False):
        fontname = "helv" if not bold else "helv"
        self.page.insert_text((x, y), str(value), fontsize=size, fontname=fontname, color=color)

    def footer(self):
        footer_text = f"Gastou Lembrou 2026 - Pagina {self.page.number + 1}"
        self.page.draw_line((MARGIN, PAGE_HEIGHT - 34), (PAGE_WIDTH - MARGIN, PAGE_HEIGHT - 34), color=BORDER, width=0.6)
        self.text(footer_text, MARGIN, PAGE_HEIGHT - 18, size=8, color=MUTED)


def format_currency(value):
    amount = Decimal(value or 0)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"
