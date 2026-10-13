from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from .card_cycles import statement_closing_date, statement_due_date


class SundayClosingTests(SimpleTestCase):
    def test_october_sunday_closes_on_saturday(self):
        card = SimpleNamespace(closing_day=4, due_day=10)
        self.assertEqual(statement_closing_date(card, date(2026, 10, 1)), date(2026, 10, 3))
        self.assertEqual(statement_due_date(card, date(2026, 10, 2)), date(2026, 10, 10))
        for day in (3, 4, 5):
            self.assertEqual(statement_due_date(card, date(2026, 10, day)), date(2026, 11, 10))
        self.assertEqual(card.closing_day, 4)

    def test_other_weekdays_stay_unchanged(self):
        card = SimpleNamespace(closing_day=4, due_day=10)
        self.assertEqual(statement_closing_date(card, date(2026, 11, 1)), date(2026, 11, 4))
        self.assertEqual(statement_due_date(card, date(2026, 11, 3)), date(2026, 11, 10))
        self.assertEqual(statement_due_date(card, date(2026, 11, 4)), date(2026, 12, 10))

    def test_first_day_sunday_can_close_in_previous_month(self):
        card = SimpleNamespace(closing_day=1, due_day=10)
        self.assertEqual(statement_closing_date(card, date(2026, 11, 1)), date(2026, 10, 31))
        self.assertEqual(statement_due_date(card, date(2026, 10, 30)), date(2026, 11, 10))
        self.assertEqual(statement_due_date(card, date(2026, 10, 31)), date(2026, 12, 10))

    def test_short_month_sunday_and_year_rollover(self):
        card = SimpleNamespace(closing_day=31, due_day=5)
        self.assertEqual(statement_closing_date(card, date(2027, 2, 1)), date(2027, 2, 27))
        self.assertEqual(statement_due_date(card, date(2027, 2, 26)), date(2027, 3, 5))
        self.assertEqual(statement_due_date(card, date(2027, 2, 27)), date(2027, 4, 5))
        self.assertEqual(statement_closing_date(card, date(2028, 12, 1)), date(2028, 12, 30))
        self.assertEqual(statement_due_date(card, date(2028, 12, 30)), date(2029, 2, 5))

    def test_due_day_is_not_shifted_or_reassigned(self):
        card = SimpleNamespace(closing_day=4, due_day=4)
        self.assertEqual(statement_due_date(card, date(2026, 10, 2)), date(2026, 11, 4))
        card.due_day = 11
        self.assertEqual(statement_due_date(card, date(2026, 10, 2)), date(2026, 10, 11))
