from django.contrib import admin

from .models import Category, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod, PaymentNotification


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "created_at")
    search_fields = ("name", "user__email")
    list_filter = ("user", "created_at")


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "category", "kind", "amount", "payment_method", "is_installment", "payment_date", "scheduled_date", "imported_at")
    search_fields = ("title", "user__email", "category__name", "payment_method__name", "import_hash")
    list_filter = ("kind", "is_installment", "category", "payment_method", "payment_date", "scheduled_date")


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "created_at")
    search_fields = ("name",)
    list_filter = ("created_at",)


@admin.register(CreditCardStatement)
class CreditCardStatementAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "parser_source", "created_at")
    search_fields = ("user__email", "error_message")
    list_filter = ("status", "parser_source", "created_at")


@admin.register(CreditCardStatementItem)
class CreditCardStatementItemAdmin(admin.ModelAdmin):
    list_display = ("title", "statement", "amount", "payment_date", "status", "payment")
    search_fields = ("title", "statement__user__email", "import_hash")
    list_filter = ("status", "payment_date", "created_at")


@admin.register(PaymentNotification)
class PaymentNotificationAdmin(admin.ModelAdmin):
    list_display = ("payment", "kind", "scheduled_date", "sent_at")
    search_fields = ("payment__title", "payment__user__email")
    list_filter = ("kind", "scheduled_date", "sent_at")
