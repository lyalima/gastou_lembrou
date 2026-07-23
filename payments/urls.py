from django.urls import path

from .views import (
    CategoryCreateView,
    BankStatementImportView,
    CreditCardStatementConfirmView,
    CreditCardStatementImportView,
    PaymentCreateView,
    PaymentDeleteView,
    PaymentDetailView,
    PaymentListView,
    PaymentReceiptView,
    PaymentUpdateView,
)

app_name = "payments"

urlpatterns = [
    path("", PaymentListView.as_view(), name="list"),
    path("novo/", PaymentCreateView.as_view(), name="create"),
    path("importar-extrato/", BankStatementImportView.as_view(), name="statement_import"),
    path("importar-fatura-cartao/", CreditCardStatementImportView.as_view(), name="credit_card_statement_import"),
    path("faturas-cartao/<int:pk>/confirmar/", CreditCardStatementConfirmView.as_view(), name="credit_card_statement_confirm"),
    path("categorias/nova/", CategoryCreateView.as_view(), name="category_create"),
    path("<uuid:pk>/arquivo/", PaymentReceiptView.as_view(), name="receipt"),
    path("<uuid:pk>/", PaymentDetailView.as_view(), name="detail"),
    path("<uuid:pk>/editar/", PaymentUpdateView.as_view(), name="update"),
    path("<uuid:pk>/excluir/", PaymentDeleteView.as_view(), name="delete"),
]
