from django.conf import settings
from django.db import models


class FinancialInsightSnapshot(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Processando"
        READY = "ready", "Pronto"
        ERROR = "error", "Erro"

    class Source(models.TextChoices):
        GEMINI = "gemini", "Gemini"
        LOCAL = "local", "Análise local"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="financial_insights")
    period_key = models.CharField(max_length=7)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=16, choices=Source.choices, blank=True)
    insights = models.JSONField(default=list, blank=True)
    summary = models.CharField(max_length=240, blank=True)
    error_message = models.CharField(max_length=240, blank=True)
    generated_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "period_key"), name="unique_financial_insight_snapshot_period"),
        ]

    def __str__(self):
        return f"{self.user} - {self.period_key}"

    @property
    def display_summary(self):
        from .insights import normalize_pt_br_text

        return normalize_pt_br_text(self.summary)

    @property
    def display_insights(self):
        from .insights import normalize_insight_result

        return normalize_insight_result({"insights": self.insights}).get("insights", [])


class MonthlySpendingGoal(models.Model):
    class AlertThreshold(models.IntegerChoices):
        FIFTY = 50, "50%"
        SEVENTY_FIVE = 75, "75%"
        NINETY = 90, "90%"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="monthly_spending_goals")
    period_month = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    alert_threshold = models.PositiveSmallIntegerField(choices=AlertThreshold.choices, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "period_month"), name="unique_monthly_spending_goal_per_user_month"),
        ]

    def __str__(self):
        return f"Meta mensal de {self.user} - {self.period_month:%m/%Y}"


class SpendingGoalNotification(models.Model):
    goal = models.ForeignKey(MonthlySpendingGoal, on_delete=models.CASCADE, related_name="notifications")
    period_key = models.CharField(max_length=7)
    threshold = models.PositiveSmallIntegerField(choices=MonthlySpendingGoal.AlertThreshold.choices)
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-sent_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("goal", "period_key", "threshold"),
                name="unique_spending_goal_notification_per_month",
            ),
        ]

    def __str__(self):
        return f"{self.goal} - {self.period_key} - {self.threshold}%"
