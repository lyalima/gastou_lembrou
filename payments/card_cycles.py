import calendar
from datetime import timedelta

from .installments import add_months


def day_in_month(value, day):
    return value.replace(day=min(day, calendar.monthrange(value.year, value.month)[1]))


def statement_closing_date(card, month):
    closing = day_in_month(month, card.closing_day)
    return closing - timedelta(days=1) if closing.weekday() == 6 else closing


def statement_due_date(card, purchase_date):
    """Purchases on the closing day belong to the next statement."""
    month = purchase_date.replace(day=1)
    while purchase_date >= statement_closing_date(card, month):
        month = add_months(month, 1)
    # Keep the nominal cycle for due dates, even if Sunday shifts closing
    # into the previous month. Only the purchase cutoff moves.
    closing = day_in_month(month, card.closing_day)
    due = day_in_month(closing, card.due_day)
    if due <= closing:
        due = day_in_month(add_months(closing.replace(day=1), 1), card.due_day)
    return due
