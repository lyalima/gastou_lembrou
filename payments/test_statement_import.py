from datetime import date
from decimal import Decimal

import fitz
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .forms import PaymentForm
from .models import Category, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod


User = get_user_model()


class StatementImportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.other = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        self.global_category = Category.objects.create(name="Mercado")
        for user in (self.user, self.other):
            LegalAcceptance.objects.create(
                user=user,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
                source=LegalAcceptance.Source.EMAIL,
            )

    def test_common_user_can_create_private_category(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:category_create"),
            {"name": "Viagens", "description": "Gastos de viagem"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(user=self.user, name="Viagens").exists())

    def test_payment_form_lists_global_and_own_categories_only(self):
        own_category = Category.objects.create(user=self.user, name="Minha categoria")
        other_category = Category.objects.create(user=self.other, name="Categoria privada")

        form = PaymentForm(user=self.user)

        self.assertIn(self.global_category, form.fields["category"].queryset)
        self.assertIn(own_category, form.fields["category"].queryset)
        self.assertNotIn(other_category, form.fields["category"].queryset)

    def test_import_csv_statement_creates_expense_payments_and_skips_income(self):
        upload = SimpleUploadedFile(
            "extrato.csv",
            "Data;Descrição;Valor\n10/07/2026;Mercado Central;-123,45\n11/07/2026;Salário;2500,00\n".encode("utf-8"),
            content_type="text/csv",
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse("payments:statement_import"), {"statement_file": upload})

        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(user=self.user, title="Mercado Central")
        self.assertEqual(payment.amount, Decimal("123.45"))
        self.assertEqual(payment.payment_date, date(2026, 7, 10))
        self.assertTrue(payment.import_hash)
        self.assertFalse(Payment.objects.filter(title="Salário").exists())

    def test_import_statement_does_not_duplicate_existing_transactions(self):
        content = "Data;Descrição;Valor\n10/07/2026;Mercado Central;-123,45\n".encode("utf-8")
        self.client.force_login(self.user)

        self.client.post(reverse("payments:statement_import"), {"statement_file": SimpleUploadedFile("extrato.csv", content, content_type="text/csv")})
        self.client.post(reverse("payments:statement_import"), {"statement_file": SimpleUploadedFile("extrato.csv", content, content_type="text/csv")})

        self.assertEqual(Payment.objects.filter(user=self.user, title="Mercado Central").count(), 1)

    def test_import_ofx_statement_creates_expense_payment(self):
        ofx = b"""
        <OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
        <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260712<TRNAMT>-45.90<FITID>abc123<MEMO>Padaria
        </BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
        """
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.ofx", ofx, content_type="application/x-ofx")},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(user=self.user, title="Padaria", amount=Decimal("45.90")).exists())

    def test_import_statement_marks_credit_card_bill(self):
        upload = SimpleUploadedFile(
            "extrato.csv",
            "Data;Descrição;Valor\n10/07/2026;Pagamento fatura cartão;-500,00\n".encode("utf-8"),
            content_type="text/csv",
        )
        self.client.force_login(self.user)

        self.client.post(reverse("payments:statement_import"), {"statement_file": upload})

        payment = Payment.objects.get(user=self.user, title="Pagamento fatura cartão")
        self.assertEqual(payment.kind, Payment.Kind.CREDIT_CARD_BILL)

    def test_payment_with_credit_card_bill_category_is_classified_as_bill(self):
        bill_category = Category.objects.create(user=self.user, name="Fatura de Cartão de Crédito")

        payment = Payment.objects.create(
            user=self.user,
            category=bill_category,
            title="Pagamento do mês",
            amount=Decimal("500.00"),
        )

        self.assertEqual(payment.kind, Payment.Kind.CREDIT_CARD_BILL)

    def test_payment_form_classifies_credit_card_bill_category(self):
        bill_category = Category.objects.create(user=self.user, name="Fatura de Cartão de Crédito")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Pagamento da fatura",
                "category": bill_category.pk,
                "kind": Payment.Kind.EXPENSE,
                "amount": "500.00",
                "payment_date": "2026-07-10",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        payment.user = self.user
        payment.save()

        self.assertEqual(payment.kind, Payment.Kind.CREDIT_CARD_BILL)

    def test_credit_card_payment_can_be_marked_as_installment(self):
        card_method = PaymentMethod.objects.create(name="Cartão de crédito")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Compra parcelada",
                "category": self.global_category.pk,
                "amount": "300.00",
                "payment_method": card_method.pk,
                "is_installment": "on",
                "payment_date": "2026-07-10",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        payment.user = self.user
        payment.save()

        self.assertTrue(payment.is_installment)

    def test_non_credit_card_payment_clears_installment_flag(self):
        pix_method = PaymentMethod.objects.create(name="Pix")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Compra no pix",
                "category": self.global_category.pk,
                "amount": "80.00",
                "payment_method": pix_method.pk,
                "is_installment": "on",
                "payment_date": "2026-07-10",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        payment.user = self.user
        payment.save()

        self.assertFalse(payment.is_installment)

    @override_settings(GEMINI_API_KEY="")
    def test_credit_card_statement_upload_shows_preview_without_creating_payments(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:credit_card_statement_import"),
            {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )

        statement = CreditCardStatement.objects.get(user=self.user)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(statement.status, CreditCardStatement.Status.READY)
        self.assertContains(response, "Mercado Central")
        self.assertContains(response, "Confirmar importação")
        self.assertEqual(Payment.objects.filter(user=self.user, title="Mercado Central").count(), 0)

    @override_settings(GEMINI_API_KEY="")
    def test_credit_card_statement_confirm_creates_credit_card_payments(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("payments:credit_card_statement_import"),
            {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )
        statement = CreditCardStatement.objects.get(user=self.user)
        item = statement.items.get(title="Mercado Central")

        response = self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {
                "items": [str(item.pk)],
                f"title_{item.pk}": "Mercado Central",
                f"date_{item.pk}": "2026-07-10",
                f"amount_{item.pk}": "123,45",
                f"category_{item.pk}": self.global_category.pk,
            },
            HTTP_HX_REQUEST="true",
        )

        payment = Payment.objects.get(user=self.user, title="Mercado Central")
        item.refresh_from_db()
        statement.refresh_from_db()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertEqual(payment.amount, Decimal("123.45"))
        self.assertEqual(payment.kind, Payment.Kind.EXPENSE)
        self.assertFalse(payment.is_installment)
        self.assertEqual(payment.payment_method.name, "Cartão de crédito")
        self.assertEqual(payment.credit_card_statement, statement)
        self.assertEqual(payment.category, self.global_category)
        self.assertEqual(item.status, CreditCardStatementItem.Status.IMPORTED)
        self.assertEqual(statement.status, CreditCardStatement.Status.CONFIRMED)

    @override_settings(GEMINI_API_KEY="")
    def test_credit_card_statement_confirm_skips_duplicates(self):
        card_method = PaymentMethod.objects.create(name="Cartão de crédito")
        self.client.force_login(self.user)
        self.client.post(
            reverse("payments:credit_card_statement_import"),
            {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )
        statement = CreditCardStatement.objects.get(user=self.user)
        item = statement.items.get(title="Mercado Central")
        Payment.objects.create(
            user=self.user,
            title=item.title,
            amount=item.amount,
            payment_date=item.payment_date,
            payment_method=card_method,
        )

        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {
                "items": [str(item.pk)],
                f"title_{item.pk}": item.title,
                f"date_{item.pk}": item.payment_date.strftime("%Y-%m-%d"),
                f"amount_{item.pk}": "123,45",
            },
            HTTP_HX_REQUEST="true",
        )

        item.refresh_from_db()
        self.assertEqual(Payment.objects.filter(user=self.user, title="Mercado Central").count(), 1)
        self.assertEqual(item.status, CreditCardStatementItem.Status.SKIPPED)


def _credit_card_pdf_bytes():
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    text = "\n".join(
        [
            "Fatura de cartao de credito",
            "Lancamentos da fatura",
            "10/07/2026 Mercado Central R$ 123,45",
            "11/07/2026 Farmacia Boa Saude R$ 45,90",
            "Pagamento recebido R$ 500,00",
            "Total da fatura R$ 169,35",
            "Texto complementar para garantir extracao suficiente do PDF digital.",
            "Este documento contem compras, datas, descricoes e valores para teste automatizado.",
            "Linha adicional de contexto da fatura do cartao de credito com texto selecionavel.",
            "Mais informacoes da fatura para ultrapassar o limite minimo de leitura do parser.",
        ]
    )
    page.insert_textbox(fitz.Rect(45, 45, 550, 500), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data
