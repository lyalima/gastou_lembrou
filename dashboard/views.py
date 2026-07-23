from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from .forms import MonthlySpendingGoalForm
from .insights import build_insight_dataset, local_insights
from .metrics import default_report_month, get_available_report_months, get_dashboard_metrics, parse_report_month
from .models import FinancialInsightSnapshot, MonthlySpendingGoal
from .reports import build_dashboard_report_pdf
from .tasks import queue_financial_insights, queue_spending_goal_alert_check


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        selected_dashboard_month = parse_report_month(self.request.GET.get("month"))
        context.update(get_dashboard_metrics(self.request.user, month=selected_dashboard_month))
        report_months = get_available_report_months(self.request.user)
        default_month = default_report_month(self.request.user)
        selected_month = (
            selected_dashboard_month.strftime("%Y-%m")
            if selected_dashboard_month
            else report_months[0]["value"] if report_months else default_month.strftime("%Y-%m")
        )
        context["dashboard_months"] = report_months
        context["selected_dashboard_month"] = selected_dashboard_month.strftime("%Y-%m") if selected_dashboard_month else ""
        context["report_months"] = report_months
        context["selected_report_month"] = selected_month
        context["selected_report_month_label"] = default_month.strftime("%m/%Y")
        period_key = selected_dashboard_month.strftime("%Y-%m") if selected_dashboard_month else "all"
        context["insight_period_key"] = period_key
        context["insight_period_label"] = selected_dashboard_month.strftime("%m/%Y") if selected_dashboard_month else "todos os períodos"
        # Insights are intentionally ephemeral in the UI. A fresh dashboard
        # request always starts closed, even if a prior snapshot is cached.
        context["insight_snapshot"] = None
        goal_month = selected_dashboard_month or _current_month()
        context.update(_spending_goal_context(self.request.user, goal_month))
        return context


class DashboardReportPDFView(LoginRequiredMixin, View):
    def get(self, request):
        report_month = parse_report_month(request.GET.get("month")) or default_report_month(request.user)
        pdf = build_dashboard_report_pdf(request.user, report_month)
        response = HttpResponse(pdf, content_type="application/pdf")
        filename = f"relatorio-gastou-lembrou-{report_month.strftime('%Y-%m')}.pdf"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class MonthlySpendingGoalView(LoginRequiredMixin, View):
    template_name = "dashboard/partials/spending_goal_form.html"

    def get(self, request):
        goal_month = _goal_month_from_request(request)
        goal = MonthlySpendingGoal.objects.filter(user=request.user, period_month=goal_month).first()
        form = MonthlySpendingGoalForm(instance=goal)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "goal": goal,
                "goal_month": goal_month,
                "goal_month_value": goal_month.strftime("%Y-%m"),
                "goal_month_label": goal_month.strftime("%m/%Y"),
            },
        )

    def post(self, request):
        goal_month = _goal_month_from_request(request)
        goal = MonthlySpendingGoal.objects.filter(user=request.user, period_month=goal_month).first()
        form = MonthlySpendingGoalForm(request.POST, instance=goal)
        if form.is_valid():
            goal = form.save(commit=False)
            goal.user = request.user
            goal.period_month = goal_month
            goal.save()
            queue_spending_goal_alert_check(request.user.pk, goal_month)
            messages.success(request, "Meta mensal salva.")
            if request.headers.get("HX-Request"):
                response = HttpResponse(status=204)
                response["HX-Refresh"] = "true"
                return response
            if request.GET.get("month"):
                return redirect(f"{request.build_absolute_uri('/dashboard/')}?month={goal_month.strftime('%Y-%m')}")
            return redirect("dashboard:home")
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "goal": goal,
                "goal_month": goal_month,
                "goal_month_value": goal_month.strftime("%Y-%m"),
                "goal_month_label": goal_month.strftime("%m/%Y"),
            },
        )


@login_required
@require_POST
def generate_insights_view(request):
    period_key = request.POST.get("period", "all")
    if period_key != "all" and not parse_report_month(period_key):
        period_key = "all"

    snapshot, _ = FinancialInsightSnapshot.objects.update_or_create(
        user=request.user,
        period_key=period_key,
        defaults={
            "status": FinancialInsightSnapshot.Status.PENDING,
            "source": "",
            "insights": [],
            "summary": "",
            "error_message": "",
            "generated_at": None,
        },
    )
    queue_financial_insights(snapshot.pk)
    snapshot.refresh_from_db()

    if request.headers.get("HX-Request"):
        return render(
            request,
            "dashboard/partials/insights.html",
            _insight_context(snapshot, period_key),
        )
    dashboard_url = "dashboard:home"
    if period_key == "all":
        return redirect(dashboard_url)
    return redirect(f"{request.build_absolute_uri('/dashboard/')}?month={period_key}")


@login_required
def insight_status_view(request, pk):
    snapshot = get_object_or_404(FinancialInsightSnapshot, pk=pk, user=request.user)
    stale_before = timezone.now() - timezone.timedelta(seconds=45)
    if snapshot.status == FinancialInsightSnapshot.Status.PENDING and snapshot.updated_at <= stale_before:
        result = local_insights(build_insight_dataset(snapshot.user, snapshot.period_key))
        snapshot.status = FinancialInsightSnapshot.Status.READY
        snapshot.source = FinancialInsightSnapshot.Source.LOCAL
        snapshot.summary = result["summary"]
        snapshot.insights = result["insights"]
        snapshot.error_message = ""
        snapshot.generated_at = timezone.now()
        snapshot.save(
            update_fields=[
                "status",
                "source",
                "summary",
                "insights",
                "error_message",
                "generated_at",
                "updated_at",
            ]
        )
    response = render(
        request,
        "dashboard/partials/insights.html",
        _insight_context(snapshot, snapshot.period_key),
    )
    if snapshot.status != FinancialInsightSnapshot.Status.PENDING:
        response.status_code = 286
    return response


def _insight_context(snapshot, period_key):
    selected_month = parse_report_month(period_key) if period_key != "all" else None
    return {
        "insight_snapshot": snapshot,
        "insight_period_key": period_key,
        "insight_period_label": selected_month.strftime("%m/%Y") if selected_month else "todos os períodos",
    }


def _current_month():
    today = timezone.localdate()
    return today.replace(day=1)


def _spending_goal_context(user, month):
    monthly_metrics = get_dashboard_metrics(user, month=month)
    spent = monthly_metrics["total"]
    goal = MonthlySpendingGoal.objects.filter(user=user, period_month=month).first()
    goal_amount = goal.amount if goal else 0
    percentage = 0
    if goal_amount:
        percentage = min(round((spent / goal_amount) * 100), 999)
    if percentage <= 50:
        progress_status = "success"
    elif percentage <= 70:
        progress_status = "warning"
    else:
        progress_status = "danger"

    return {
        "spending_goal": goal,
        "spending_goal_month": month,
        "spending_goal_month_label": month.strftime("%m/%Y"),
        "spending_goal_period_key": month.strftime("%Y-%m"),
        "spending_goal_spent": spent,
        "spending_goal_amount": goal_amount,
        "spending_goal_percentage": percentage,
        "spending_goal_bar_width": min(percentage, 100),
        "spending_goal_status": progress_status,
    }


def _goal_month_from_request(request):
    return parse_report_month(request.POST.get("month") or request.GET.get("month")) or _current_month()
