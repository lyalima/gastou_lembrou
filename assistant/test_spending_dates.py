import json
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from dashboard.metrics import get_dashboard_metrics
from dashboard.models import MonthlySpendingGoal
from payments.models import Category, CreditCard, Payment, PaymentMethod
from .services import _future_installments_answer
from .tools import build_spike_tools


class SpikeSpendingDateTests(TestCase):
    def test_tools_match_dashboard_and_keep_invoice_date_separate(self):
        user = get_user_model().objects.create_user(email="dates@example.test")
        other = get_user_model().objects.create_user(email="other-dates@example.test")
        category = Category.objects.create(name="Mercado")
        method = PaymentMethod.objects.create(name="Cartão de crédito")
        card = CreditCard.objects.create(user=user, name="Principal", closing_day=19, due_day=25)
        purchase = Payment.objects.create(user=user, title="Compra", amount=60, category=category,
                                         payment_method=method, credit_card=card, payment_date=date(2026, 9, 21))
        Payment.objects.create(user=other, title="Privado", amount=999, category=category, payment_date=date(2026, 9, 21))
        Payment.objects.create(user=user, title="Fatura", amount=60, kind=Payment.Kind.CREDIT_CARD_BILL, payment_date=date(2026, 9, 25))
        MonthlySpendingGoal.objects.create(user=user, period_month=date(2026, 9, 1), amount=100)
        tools = {tool.name: tool for tool in build_spike_tools(user)}
        period = {"data_inicial": "2026-09-01", "data_final": "2026-09-30"}
        summary = json.loads(tools["resumir_gastos"].invoke(period))
        self.assertEqual(Decimal(summary["total"]), get_dashboard_metrics(user, date(2026, 9, 1))["total"])
        self.assertEqual(summary["quantidade"], 1)
        records = json.loads(tools["buscar_pagamentos"].invoke(period))["pagamentos"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data_financeira"], "2026-09-21")
        self.assertEqual(records[0]["vencimento_fatura"], "2026-10-25")
        october = json.loads(tools["resumir_gastos"].invoke({"data_inicial": "2026-10-01", "data_final": "2026-10-31"}))
        self.assertEqual(october["quantidade"], 0)
        ranking = json.loads(tools["analisar_ranking"].invoke({**period, "dimensao": "categoria"}))["ranking"]
        self.assertEqual(Decimal(ranking[0]["total"]), 60)
        evolution = json.loads(tools["evolucao_de_gastos"].invoke(period))["evolucao"]
        self.assertEqual(evolution[0]["mes"], "09/2026")
        self.assertEqual(Decimal(evolution[0]["total"]), 60)
        goal = json.loads(tools["consultar_meta"].invoke({"mes": "2026-09"}))
        self.assertEqual(Decimal(goal["gasto"]), 60)
        self.assertEqual(Decimal(goal["percentual"]), 60)
        Payment.objects.filter(pk=purchase.pk).update(is_installment=True)
        with patch("assistant.services.timezone.localdate", return_value=date(2026, 9, 22)):
            self.assertIn("não tem parcelas futuras", _future_installments_answer(user))

    def test_noncredit_uses_scheduled_date_before_payment_date(self):
        user = get_user_model().objects.create_user(email="scheduled-dates@example.test")
        Payment.objects.create(user=user, title="Previsto", amount=20, payment_date=date(2026, 9, 20), scheduled_date=date(2026, 10, 2))
        tools = {tool.name: tool for tool in build_spike_tools(user)}
        result = json.loads(tools["resumir_gastos"].invoke({"data_inicial": "2026-10-01", "data_final": "2026-10-31"}))
        self.assertEqual(Decimal(result["total"]), 20)
