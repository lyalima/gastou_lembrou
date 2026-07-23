from django.contrib import admin

from .models import FinancialInsightSnapshot, MonthlySpendingGoal, SpendingGoalNotification


@admin.register(FinancialInsightSnapshot)
class FinancialInsightSnapshotAdmin(admin.ModelAdmin):
    list_display = ("user", "period_key", "status", "source", "generated_at", "updated_at")
    list_filter = ("status", "source", "period_key")
    search_fields = ("user__email", "summary")
    readonly_fields = ("created_at", "updated_at", "generated_at")


@admin.register(MonthlySpendingGoal)
class MonthlySpendingGoalAdmin(admin.ModelAdmin):
    list_display = ("user", "period_month", "amount", "alert_threshold", "updated_at")
    list_filter = ("period_month", "alert_threshold")
    search_fields = ("user__email",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(SpendingGoalNotification)
class SpendingGoalNotificationAdmin(admin.ModelAdmin):
    list_display = ("goal", "period_key", "threshold", "sent_at")
    list_filter = ("period_key", "threshold")
    search_fields = ("goal__user__email",)
    readonly_fields = ("sent_at",)
