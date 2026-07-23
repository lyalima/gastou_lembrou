import fitz
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from payments.models import Category, Payment, PaymentMethod
from .insights import build_insight_dataset, gemini_insights, generate_insights, normalize_pt_br_text
from .models import FinancialInsightSnapshot, MonthlySpendingGoal, SpendingGoalNotification
from .tasks import check_spending_goal_alert, previous_month, send_previous_month_reports, send_spending_goal_alerts


User = get_user_model()


class DashboardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Mercado")
        self.payment_method = PaymentMethod.objects.create(name="Pix")

    def test_dashboard_includes_payment_method_metrics(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Antigo",
            amount=Decimal("20.00"),
            payment_date=date(2026, 5, 11),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertContains(response, "Gastos por forma de pagamento")
        self.assertContains(response, "Pix")
        self.assertContains(response, "Sem forma")
        self.assertEqual(response.context["payment_method_labels"], ["Sem forma", "Pix"])
        self.assertEqual(response.context["payment_method_totals"], [20.0, 30.0])

    def test_dashboard_ignores_credit_card_bill_payments_in_expense_metrics(self):
        credit_card = PaymentMethod.objects.create(name="Cartão de crédito")
        bill_category = Category.objects.create(user=self.user, name="Fatura de Cartão de Crédito")
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=credit_card,
            title="Compra no mercado",
            amount=Decimal("200.00"),
            payment_date=date(2026, 7, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=bill_category,
            payment_method=self.payment_method,
            kind=Payment.Kind.CREDIT_CARD_BILL,
            title="Fatura do cartão",
            amount=Decimal("200.00"),
            payment_date=date(2026, 7, 20),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"), {"month": "2026-07"})

        self.assertEqual(response.context["total"], Decimal("200.00"))
        self.assertEqual(response.context["payment_count"], 1)
        self.assertEqual(response.context["category_labels"], ["Mercado"])
        self.assertEqual(response.context["payment_method_labels"], ["Cartão de crédito"])
        self.assertEqual(response.context["payment_method_totals"], [200.0])
        self.assertContains(response, "Compra no mercado")
        self.assertNotContains(response, "Fatura do cartão")

    def test_dashboard_has_pdf_report_button(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertContains(response, reverse("dashboard:report_pdf"))
        self.assertContains(response, "Mês do dashboard")
        self.assertContains(response, "Ver tudo")
        self.assertContains(response, 'name="month"')
        self.assertContains(response, "Gerar relat")
        self.assertContains(response, "Insights inteligentes")
        self.assertContains(response, "Gerar análise")
        self.assertContains(response, reverse("dashboard:spending_goal"))
        self.assertContains(response, "Definir meta")
        self.assertContains(response, "Meta de gastos mensal")
        self.assertContains(response, "R$ 0,00")

    def test_user_can_create_monthly_spending_goal_from_modal(self):
        self.client.force_login(self.user)

        get_response = self.client.get(reverse("dashboard:spending_goal"), HTTP_HX_REQUEST="true")
        post_response = self.client.post(
            reverse("dashboard:spending_goal"),
            {"amount": "R$ 1.200,00", "alert_threshold": "75"},
            HTTP_HX_REQUEST="true",
        )

        goal = MonthlySpendingGoal.objects.get(user=self.user, period_month=timezone.localdate().replace(day=1))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Definir meta de gastos")
        self.assertEqual(post_response.status_code, 204)
        self.assertEqual(post_response["HX-Refresh"], "true")
        self.assertEqual(goal.amount, Decimal("1200.00"))
        self.assertEqual(goal.alert_threshold, 75)

    def test_dashboard_shows_spending_goal_progress_for_selected_month(self):
        MonthlySpendingGoal.objects.create(user=self.user, period_month=date(2026, 5, 1), amount=Decimal("100.00"), alert_threshold=90)
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("75.00"),
            payment_date=date(2026, 5, 10),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"), {"month": "2026-05"})

        self.assertContains(response, "Meta de gastos mensal")
        self.assertContains(response, "Acompanhamento da meta em 05/2026")
        self.assertContains(response, "75%")
        self.assertContains(response, "spending-goal-progress-danger")

    def test_dashboard_uses_goal_for_selected_month_only(self):
        MonthlySpendingGoal.objects.create(user=self.user, period_month=date(2026, 7, 1), amount=Decimal("1000.00"))
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Gasto julho",
            amount=Decimal("160.00"),
            payment_date=date(2026, 7, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Gasto junho",
            amount=Decimal("1200.00"),
            payment_date=date(2026, 6, 10),
        )
        self.client.force_login(self.user)

        july_response = self.client.get(reverse("dashboard:home"), {"month": "2026-07"})
        june_response = self.client.get(reverse("dashboard:home"), {"month": "2026-06"})

        self.assertContains(july_response, "16%")
        self.assertContains(july_response, "R$ 1000,00")
        self.assertContains(june_response, "Acompanhamento da meta em 06/2026")
        self.assertContains(june_response, "R$ 0,00")
        self.assertContains(june_response, "0%")
        self.assertContains(june_response, "Nenhuma meta definida para este mês.")

    def test_spending_goal_alert_email_is_sent_once_per_month_threshold(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("55.00"),
            payment_date=date(2026, 5, 10),
        )
        goal = MonthlySpendingGoal.objects.create(user=self.user, period_month=date(2026, 5, 1), amount=Decimal("100.00"), alert_threshold=50)

        first_result = check_spending_goal_alert(self.user.pk, "2026-05")
        second_result = check_spending_goal_alert(self.user.pk, "2026-05")

        self.assertTrue(first_result)
        self.assertFalse(second_result)
        self.assertEqual(SpendingGoalNotification.objects.filter(goal=goal, period_key="2026-05", threshold=50).count(), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("50%", mail.outbox[0].subject)
        self.assertIn("R$ 100,00", mail.outbox[0].body)

    def test_spending_goal_alert_scan_sends_missed_alerts(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("725.34"),
            payment_date=date(2026, 7, 10),
        )
        goal = MonthlySpendingGoal.objects.create(
            user=self.user,
            period_month=date(2026, 7, 1),
            amount=Decimal("1000.00"),
            alert_threshold=50,
        )

        first_count = send_spending_goal_alerts()
        second_count = send_spending_goal_alerts()

        self.assertEqual(first_count, 1)
        self.assertEqual(second_count, 0)
        self.assertEqual(SpendingGoalNotification.objects.filter(goal=goal, period_key="2026-07", threshold=50).count(), 1)
        self.assertEqual(len(mail.outbox), 1)

    def test_fresh_dashboard_request_does_not_reopen_previous_insights(self):
        FinancialInsightSnapshot.objects.create(
            user=self.user,
            period_key="all",
            status=FinancialInsightSnapshot.Status.READY,
            source=FinancialInsightSnapshot.Source.LOCAL,
            summary="Resumo que não deve reaparecer.",
            insights=[
                {
                    "title": "Insight anterior",
                    "body": "Conteúdo anterior.",
                    "kind": "general",
                    "priority": "info",
                }
            ],
            generated_at=timezone.now(),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertIsNone(response.context["insight_snapshot"])
        self.assertContains(response, "Gerar análise")
        self.assertNotContains(response, "Resumo que não deve reaparecer")
        self.assertNotContains(response, "Insight anterior")

    @override_settings(GEMINI_API_KEY="", CELERY_TASK_ALWAYS_EAGER=True)
    def test_generate_insights_uses_local_fallback_and_saves_snapshot(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("dashboard:generate_insights"),
            {"period": "2026-05"},
            HTTP_HX_REQUEST="true",
        )

        snapshot = FinancialInsightSnapshot.objects.get(user=self.user, period_key="2026-05")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(snapshot.status, FinancialInsightSnapshot.Status.READY)
        self.assertEqual(snapshot.source, FinancialInsightSnapshot.Source.LOCAL)
        self.assertTrue(snapshot.insights)
        self.assertContains(response, "Análise automática local")

    def test_insight_status_is_scoped_to_authenticated_user(self):
        other_user = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        snapshot = FinancialInsightSnapshot.objects.create(
            user=other_user,
            period_key="all",
            status=FinancialInsightSnapshot.Status.READY,
            insights=[],
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:insight_status", kwargs={"pk": snapshot.pk}))

        self.assertEqual(response.status_code, 404)

    @override_settings(GEMINI_API_KEY="")
    def test_stale_pending_insight_uses_local_fallback_and_stops_polling(self):
        snapshot = FinancialInsightSnapshot.objects.create(
            user=self.user,
            period_key="all",
            status=FinancialInsightSnapshot.Status.PENDING,
        )
        FinancialInsightSnapshot.objects.filter(pk=snapshot.pk).update(
            updated_at=timezone.now() - timezone.timedelta(seconds=60)
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:insight_status", kwargs={"pk": snapshot.pk}))

        snapshot.refresh_from_db()
        self.assertEqual(response.status_code, 286)
        self.assertEqual(snapshot.status, FinancialInsightSnapshot.Status.READY)
        self.assertEqual(snapshot.source, FinancialInsightSnapshot.Source.LOCAL)
        self.assertNotContains(response, "Analisando seus pagamentos", status_code=286)

    @override_settings(GEMINI_API_KEY="")
    def test_local_insights_compare_selected_month_with_previous_month(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Abril",
            amount=Decimal("100.00"),
            payment_date=date(2026, 4, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Maio",
            amount=Decimal("130.00"),
            payment_date=date(2026, 5, 10),
        )

        dataset = build_insight_dataset(self.user, "2026-05")
        result = generate_insights(dataset)

        self.assertEqual(result["source"], "local")
        self.assertEqual(dataset["comparison"]["change_percent"], 30.0)
        self.assertIn("30.0%", result["insights"][0]["body"])
        self.assertEqual(result["insights"][0]["title"], "Variação em relação ao período anterior")
        self.assertIn("relação ao período anterior", result["insights"][0]["body"])

    def test_legacy_insight_text_is_normalized_for_display(self):
        snapshot = FinancialInsightSnapshot.objects.create(
            user=self.user,
            period_key="all",
            status=FinancialInsightSnapshot.Status.READY,
            source=FinancialInsightSnapshot.Source.GEMINI,
            summary="Analise do periodo.",
            insights=[
                {
                    "title": "Variacao em relacao ao periodo anterior",
                    "body": "Seus gastos diminuiram. Ha 2 pagamento(s) agendado(s) no periodo.",
                    "kind": "trend",
                    "priority": "info",
                }
            ],
        )

        self.assertEqual(snapshot.display_summary, "Análise do período.")
        self.assertEqual(snapshot.display_insights[0]["title"], "Variação em relação ao período anterior")
        self.assertEqual(
            snapshot.display_insights[0]["body"],
            "Seus gastos diminuíram. Há 2 pagamentos agendados no período.",
        )
        self.assertEqual(
            normalize_pt_br_text("VARIACAO EM RELACAO AO PERIODO"),
            "VARIAÇÃO EM RELAÇÃO AO PERÍODO",
        )

    @override_settings(GEMINI_API_KEY="test-key", GEMINI_MODEL="gemini-2.5-flash-lite")
    @patch("dashboard.insights.generate_content")
    def test_gemini_insights_uses_structured_generate_content_api(self, generate_content):
        generate_content.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [{
                            "text": (
                                '{"summary":"Resumo inteligente.","insights":['
                                '{"title":"Mercado em destaque","body":"Mercado concentrou os gastos.",'
                                '"kind":"category","priority":"info"}]}'
                            ),
                        }]
                    },
                }
            ]
        }

        result = gemini_insights(
            {
                "period": "all",
                "total": 30.0,
                "payment_count": 1,
                "scheduled_count": 0,
                "categories": [{"name": "Mercado", "total": 30.0, "count": 1}],
                "payment_methods": [],
                "evolution": [],
                "comparison": {},
            }
        )

        self.assertEqual(result["source"], "gemini")
        self.assertEqual(result["summary"], "Resumo inteligente.")
        request_payload = generate_content.call_args.args[0]
        self.assertIn(
            "acentuação",
            request_payload["systemInstruction"]["parts"][0]["text"],
        )
        self.assertEqual(request_payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(request_payload["generationConfig"]["responseSchema"]["type"], "object")

    def test_dashboard_month_filter_limits_metrics(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira maio",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Conta maio",
            amount=Decimal("20.00"),
            payment_date=date(2026, 5, 15),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira junho",
            amount=Decimal("70.00"),
            payment_date=date(2026, 6, 10),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"), {"month": "2026-05"})

        self.assertEqual(response.context["total"], Decimal("50.00"))
        self.assertEqual(response.context["payment_count"], 2)
        self.assertEqual(response.context["category_totals"], [50.0])
        self.assertEqual(response.context["payment_method_totals"], [50.0])
        self.assertEqual(response.context["month_labels"], ["10/05", "15/05"])
        self.assertEqual(response.context["month_totals"], [30.0, 20.0])
        self.assertEqual(response.context["evolution_title"], "Evolução ao longo do mês")
        self.assertEqual(response.context["selected_dashboard_month"], "2026-05")
        self.assertContains(response, "Evolução ao longo do mês")
        self.assertContains(response, "Feira maio")
        self.assertNotContains(response, "Feira junho")

    def test_dashboard_without_month_filter_shows_all_metrics(self):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira maio",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira junho",
            amount=Decimal("70.00"),
            payment_date=date(2026, 6, 10),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:home"))

        self.assertEqual(response.context["total"], Decimal("100.00"))
        self.assertEqual(response.context["payment_count"], 2)
        self.assertEqual(response.context["category_totals"], [100.0])
        self.assertEqual(response.context["payment_method_totals"], [100.0])
        self.assertEqual(response.context["month_labels"], ["05/2026", "06/2026"])
        self.assertEqual(response.context["evolution_title"], "Evolução mensal")
        self.assertEqual(response.context["selected_dashboard_month"], "")
        self.assertContains(response, "Evolução mensal")

    def test_dashboard_pdf_report_uses_selected_month_and_authenticated_user_metrics(self):
        other_user = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        other_category = Category.objects.create(name="Privado")
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        scheduled = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta agendada",
            amount=Decimal("80.00"),
            scheduled_date=date(2026, 5, 20),
        )
        Payment.objects.filter(pk=scheduled.pk).update(payment_date=None)
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Junho nao deve aparecer",
            amount=Decimal("70.00"),
            payment_date=date(2026, 6, 10),
        )
        Payment.objects.create(
            user=other_user,
            category=other_category,
            title="Nao deve aparecer",
            amount=Decimal("999.00"),
            payment_date=date(2026, 5, 10),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard:report_pdf"), {"month": "2026-05"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("relatorio-gastou-lembrou-2026-05.pdf", response["Content-Disposition"])
        self.assertTrue(response.content.startswith(b"%PDF"))

        document = fitz.open(stream=response.content, filetype="pdf")
        text = "\n".join(page.get_text() for page in document)
        document.close()

        self.assertIn("Relatorio mensal - 05/2026", text)
        self.assertIn("Total de Pagamentos", text)
        self.assertIn("Pagamentos agendados", text)
        self.assertIn("Gastos por categoria", text)
        self.assertIn("Categoria", text)
        self.assertIn("Gastos por forma de pagamento", text)
        self.assertIn("Forma de pagamento", text)
        self.assertIn("Mês", text)
        self.assertIn("Pagamentos", text)
        self.assertNotIn("Total de pagamentos", text)
        self.assertIn("Pagamentos registrados", text)
        self.assertIn("Feira", text)
        self.assertIn("R$ 30,00", text)
        self.assertIn("Conta agendada", text)
        self.assertIn("R$ 80,00", text)
        self.assertNotIn("Junho nao deve aparecer", text)
        self.assertNotIn("Nao deve aparecer", text)

    def test_previous_month_uses_month_before_reference_date(self):
        self.assertEqual(previous_month(date(2026, 6, 1)), date(2026, 5, 1))
        self.assertEqual(previous_month(date(2026, 1, 1)), date(2025, 12, 1))

    @patch("dashboard.tasks.timezone.localdate", return_value=date(2026, 6, 1))
    def test_monthly_report_task_sends_previous_month_pdf_only_to_users_with_payments(self, localdate):
        other_user = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Feira",
            amount=Decimal("30.00"),
            payment_date=date(2026, 5, 10),
        )
        Payment.objects.create(
            user=other_user,
            category=self.category,
            title="Fora do periodo",
            amount=Decimal("40.00"),
            payment_date=date(2026, 4, 10),
        )

        sent_count = send_previous_month_reports()

        self.assertEqual(sent_count, 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("05/2026", mail.outbox[0].subject)
        self.assertIn("relatorio-gastou-lembrou-2026-05.pdf", [attachment[0] for attachment in mail.outbox[0].attachments if isinstance(attachment, tuple)])
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
