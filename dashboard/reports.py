from decimal import Decimal
import fitz
from django.conf import settings
from django.utils import timezone

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
        self.document = fitz.open()
        self.page = None
        self.y = MARGIN

    def build(self):
        self.add_page()
        self.header()
        self.summary()
        self.metric_table("Gastos por categoria", self.metrics["category_metrics"], ("Categoria", "Qtd.", "Total"))
        self.metric_table("Evolução mensal", self.metrics["month_metrics"], ("Dia/Mês", "Pagamentos", "Total"))
        self.metric_table(
            "Gastos por forma de pagamento",
            self.metrics["payment_method_metrics"],
            ("Forma de pagamento", "Qtd.", "Total"),
        )
        self.registered_payments()
        self.footer()

    def add_page(self):
        self.page = self.document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.page.draw_rect(fitz.Rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT), color=LIGHT, fill=LIGHT)
        self.y = MARGIN

    def ensure_space(self, height):
        if self.y + height <= PAGE_HEIGHT - MARGIN:
            return
        self.footer()
        self.add_page()

    def header(self):
        logo_path = settings.BASE_DIR / "static" / "img" / "gastou-lembrou-logo.png"
        if logo_path.exists():
            self.page.insert_image(fitz.Rect(MARGIN, self.y, MARGIN + 42, self.y + 42), filename=str(logo_path))
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
        self.y += 92

    def summary(self):
        card_width = (PAGE_WIDTH - (2 * MARGIN) - 20) / 3
        cards = [
            ("Total registrado", format_currency(self.metrics["total"])),
            ("Total de Pagamentos", str(self.metrics["payment_count"])),
            ("Pagamentos agendados", str(self.metrics["scheduled_count"])),
        ]
        for index, (label, value) in enumerate(cards):
            x = MARGIN + index * (card_width + 10)
            rect = fitz.Rect(x, self.y, x + card_width, self.y + 72)
            self.page.draw_rect(rect, color=BORDER, fill=(1, 1, 1), width=0.8)
            self.text(label, x + 12, self.y + 18, size=9, color=MUTED)
            self.text(value, x + 12, self.y + 46, size=16, color=GREEN, bold=True)
        self.y += 100

    def metric_table(self, title, rows, headers):
        row_height = 24
        height = 46 + max(len(rows), 1) * row_height
        self.ensure_space(height)
        self.section_title(title)
        if not rows:
            self.empty_state("Nenhum dado registrado.")
            return
        self.table_header(headers)
        for row in rows:
            self.table_row((row["name"], str(row["count"]), format_currency(row["total"])))
        self.y += 12

    def registered_payments(self):
        payments = list(self.metrics["report_payments"])
        row_height = 34
        height = 46 + max(len(payments), 1) * row_height
        self.ensure_space(height)
        self.section_title("Pagamentos registrados")
        if not payments:
            self.empty_state("Nenhum pagamento registrado.")
            return
        self.table_header(("Pagamento", "Data", "Agend.", "Valor"))
        for payment in payments:
            payment_date = payment.payment_date.strftime("%d/%m/%Y") if payment.payment_date else "-"
            scheduled_date = payment.scheduled_date.strftime("%d/%m/%Y") if payment.scheduled_date else "-"
            title = f"{payment.title} ({payment.category.name})" if payment.category_id else payment.title
            self.table_row((title, payment_date, scheduled_date, format_currency(payment.amount)), height=row_height)

    def section_title(self, title):
        self.text(title, MARGIN, self.y, size=14, color=TEXT, bold=True)
        self.y += 24

    def table_header(self, values):
        self.page.draw_rect(fitz.Rect(MARGIN, self.y - 14, PAGE_WIDTH - MARGIN, self.y + 8), color=GREEN, fill=GREEN)
        positions = self.column_positions(len(values))
        for x, value in zip(positions, values):
            self.text(value, x, self.y, size=8.5, color=(1, 1, 1), bold=True)
        self.y += 24

    def table_row(self, values, height=24):
        self.ensure_space(height + 18)
        self.page.draw_line((MARGIN, self.y - 12), (PAGE_WIDTH - MARGIN, self.y - 12), color=BORDER, width=0.6)
        positions = self.column_positions(len(values))
        for x, value in zip(positions, values):
            text = truncate(str(value), 28 if len(values) == 4 else 40)
            self.text(text, x, self.y, size=8.5, color=TEXT)
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


def truncate(value, max_length):
    normalized = " ".join(value.split())
    if len(normalized) <= max_length:
        return normalized
    return f"{normalized[: max_length - 1]}..."
