from django.urls import path

from .views import DashboardReportPDFView, DashboardView, MonthlySpendingGoalView, generate_insights_view, insight_status_view

app_name = "dashboard"

urlpatterns = [
    path("", DashboardView.as_view(), name="home"),
    path("relatorio.pdf", DashboardReportPDFView.as_view(), name="report_pdf"),
    path("meta-mensal/", MonthlySpendingGoalView.as_view(), name="spending_goal"),
    path("insights/gerar/", generate_insights_view, name="generate_insights"),
    path("insights/<int:pk>/", insight_status_view, name="insight_status"),
]
