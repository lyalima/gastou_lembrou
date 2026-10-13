from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch

import pymupdf
from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .credit_card_statement_import import CardStatementEntry, extract_statement_due_date, parse_credit_card_entries
from .forms import PaymentForm
from .models import Category, CreditCard, CreditCardStatement, CreditCardStatementItem, Payment, PaymentMethod


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

    def confirm_bank_import(self, upload, *, selected=None, htmx=False):
        preview = self.client.post(reverse("payments:statement_import"), {"statement_file": upload})
        self.assertEqual(preview.status_code, 200)
        self.assertTemplateUsed(preview, "payments/partials/statement_import_preview.html")
        rows = preview.context["rows"]
        item_ids = [str(row["id"]) for row in rows] if selected is None else selected
        headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
        confirmation = self.client.post(
            reverse("payments:statement_confirm"),
            {"token": preview.context["token"], "items": item_ids},
            **headers,
        )
        return preview, confirmation

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

        preview, response = self.confirm_bank_import(upload)

        self.assertEqual(response.status_code, 302)
        self.assertContains(preview, "Saídas encontradas")
        payment = Payment.objects.get(user=self.user, title="Mercado Central")
        self.assertEqual(payment.amount, Decimal("123.45"))
        self.assertEqual(payment.payment_date, date(2026, 7, 10))
        self.assertTrue(payment.import_hash)
        self.assertEqual(payment.payment_method.name, "Pix")
        self.assertFalse(Payment.objects.filter(title="Salário").exists())

    def test_unrecognized_csv_keeps_import_modal_open_with_error(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.csv", b"coluna;outra\nfoo;bar\n", content_type="text/csv")},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Nenhum lançamento de despesa foi reconhecido")
        self.assertContains(response, "data-statement-analysis-form")

    def test_csv_with_only_income_reports_ignored_entries(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.csv", b"Data;Descricao;Valor\n10/07/2026;Salario;2500,00\n", content_type="text/csv")},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "Nenhuma despesa encontrada")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_csv_type_column_distinguishes_positive_debit_from_credit(self):
        content = (
            "Data da transação;Descrição;Valor (R$);Tipo de transação\n"
            "10/07/2026;Farmácia;45,90;Débito\n"
            "11/07/2026;Reembolso;20,00;Crédito\n"
        ).encode("utf-8")
        self.client.force_login(self.user)

        _, response = self.confirm_bank_import(SimpleUploadedFile("extrato.csv", content, content_type="text/csv"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(user=self.user, title="Farmácia", amount=Decimal("45.90")).exists())
        self.assertFalse(Payment.objects.filter(user=self.user, title="Reembolso").exists())

    def test_csv_with_bank_summary_before_header_imports_debits(self):
        content = (
            "Extrato Conta Corrente\n"
            "Conta;000000000\n"
            "Período;01/09/2026 a 26/09/2026\n"
            "Saldo;0,00\n\n"
            "Data Lançamento;Histórico;Descrição;Valor;Saldo\n"
            "10/09/2026;Pix enviado;Mercado exemplo;-45,90;100,00\n"
            "11/09/2026;Pix recebido;Recebimento exemplo;80,00;180,00\n"
            "12/09/2026;Saque banco 24h;Saque exemplo;-30,00;150,00\n"
            "13/09/2026;Pagamento efetuado;Pagamento fatura exemplo;-50,00;100,00\n"
        ).encode("utf-8")
        self.client.force_login(self.user)

        _, response = self.confirm_bank_import(
            SimpleUploadedFile("extrato.csv", content, content_type="text/csv"), htmx=True
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Refresh"], "true")
        self.assertTrue(Payment.objects.filter(user=self.user, title="Mercado exemplo", amount=Decimal("45.90")).exists())
        self.assertFalse(Payment.objects.filter(user=self.user, title="Recebimento exemplo").exists())
        self.assertFalse(Payment.objects.filter(user=self.user, title="Saque exemplo").exists())
        self.assertFalse(Payment.objects.filter(user=self.user, title="Pagamento fatura exemplo").exists())

    def test_bank_preview_waits_for_selection_and_imports_only_chosen_expense_as_pix(self):
        content = (
            "Data;Descrição;Valor\n"
            "10/07/2026;Mercado;-45,90\n"
            "11/07/2026;Farmácia;-20,00\n"
            "12/07/2026;Salário;100,00\n"
        ).encode("utf-8")
        self.client.force_login(self.user)
        preview = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.csv", content, content_type="text/csv")},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(preview, "Saídas para revisão:")
        self.assertEqual(len(preview.context["rows"]), 2)
        self.assertContains(preview, "Farmácia")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())
        rows = preview.context["rows"]
        selected = next(row for row in rows if row["title"] == "Farmácia")
        confirmation = self.client.post(
            reverse("payments:statement_confirm"),
            {"token": preview.context["token"], "items": [str(selected["id"])]},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(confirmation.status_code, 204)
        payment = Payment.objects.get(user=self.user)
        self.assertEqual(payment.title, "Farmácia")
        self.assertEqual(payment.payment_method.name, "Pix")

    def test_bank_preview_cannot_be_confirmed_by_another_user_or_with_unknown_item(self):
        content = "Data;Descrição;Valor\n10/07/2026;Mercado;-45,90\n".encode("utf-8")
        self.client.force_login(self.user)
        preview = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.csv", content, content_type="text/csv")},
        )
        token = preview.context["token"]
        self.client.force_login(self.other)
        foreign = self.client.post(reverse("payments:statement_confirm"), {"token": token, "items": ["0"]})
        self.assertContains(foreign, "A prévia expirou")
        self.client.force_login(self.user)
        tampered = self.client.post(reverse("payments:statement_confirm"), {"token": token, "items": ["999"]})
        self.assertContains(tampered, "Selecione pelo menos um lançamento válido")
        self.assertFalse(Payment.objects.exists())

    def test_pdf_statement_imports_debits_and_ignores_credits(self):
        document = pymupdf.open()
        page = document.new_page()
        page.insert_text((72, 72), "10/07/2026 Mercado Central -123,45\n11/07/2026 Salario 2500,00\n12/07/2026 Padaria 45,90 D")
        content = document.tobytes()
        document.close()
        self.client.force_login(self.user)

        _, response = self.confirm_bank_import(
            SimpleUploadedFile("extrato.pdf", content, content_type="application/pdf"), htmx=True
        )

        self.assertEqual(response.status_code, 204)
        self.assertTrue(Payment.objects.filter(user=self.user, title="Mercado Central", amount=Decimal("123.45")).exists())
        self.assertTrue(Payment.objects.filter(user=self.user, title="Padaria", amount=Decimal("45.90")).exists())
        self.assertFalse(Payment.objects.filter(user=self.user, title="Salario").exists())

    def test_pdf_statement_with_day_headers_and_balance_column(self):
        document = pymupdf.open()
        page = document.new_page()
        lines = (
            "4 de Setembro de 2026 Saldo do dia: R$ 100,00 Valor Saldo por transacao",
            'Pix enviado: "Mercado exemplo" -R$ 48,78 R$ 51,22',
            'Pix recebido: "Deposito exemplo" R$ 15,00 -R$ 10,00',
            "5 de Setembro de 2026 Saldo do dia: R$ 40,00",
            'Pix enviado: "Conta exemplo" -R$ 11,50 R$ 28,50',
            'Saque banco 24h: "Saque exemplo" -R$ 10,00 R$ 18,50',
            'Pagamento efetuado: "Fatura exemplo" -R$ 5,00 R$ 13,50',
        )
        for index, line in enumerate(lines):
            page.insert_text((35, 65 + index * 22), line, fontsize=9)
        content = document.tobytes()
        document.close()
        self.client.force_login(self.user)

        preview = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.pdf", content, content_type="application/pdf")},
        )

        self.assertTemplateUsed(preview, "payments/partials/statement_import_preview.html")
        rows = preview.context["rows"]
        self.assertEqual(len(rows), 2)
        self.assertEqual([(row["amount"], row["payment_date"]) for row in rows], [
            ("48.78", "2026-09-04"), ("11.50", "2026-09-05"),
        ])
        self.assertNotContains(preview, "Saque exemplo")
        self.assertNotContains(preview, "Fatura exemplo")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_scanned_pdf_reports_extractable_text_requirement(self):
        document = pymupdf.open()
        document.new_page()
        content = document.tobytes()
        document.close()
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.pdf", content, content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "não contém texto selecionável")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_fake_pdf_is_rejected(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payments:statement_import"),
            {"statement_file": SimpleUploadedFile("extrato.pdf", b"not a PDF", content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "não parece ser um PDF válido")

    def test_import_statement_does_not_duplicate_existing_transactions(self):
        content = "Data;Descrição;Valor\n10/07/2026;Mercado Central;-123,45\n".encode("utf-8")
        self.client.force_login(self.user)

        self.confirm_bank_import(SimpleUploadedFile("extrato.csv", content, content_type="text/csv"))
        second_preview = self.client.post(reverse("payments:statement_import"), {"statement_file": SimpleUploadedFile("extrato.csv", content, content_type="text/csv")})

        self.assertEqual(Payment.objects.filter(user=self.user, title="Mercado Central").count(), 1)
        self.assertContains(second_preview, "Todas as saídas deste arquivo já foram importadas.")

    def test_import_ofx_statement_creates_expense_payment(self):
        ofx = b"""
        <OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKTRANLIST>
        <STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260712<TRNAMT>-45.90<FITID>abc123<MEMO>Padaria
        </BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
        """
        self.client.force_login(self.user)

        _, response = self.confirm_bank_import(SimpleUploadedFile("extrato.ofx", ofx, content_type="application/x-ofx"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Payment.objects.filter(user=self.user, title="Padaria", amount=Decimal("45.90")).exists())

    def test_import_statement_marks_credit_card_bill(self):
        upload = SimpleUploadedFile(
            "extrato.csv",
            "Data;Descrição;Valor\n10/07/2026;Pagamento fatura cartão;-500,00\n".encode("utf-8"),
            content_type="text/csv",
        )
        self.client.force_login(self.user)

        self.confirm_bank_import(upload)

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
                "installment_total": "3",
                "installment_number": "1",
                "payment_date": "2026-07-10",
            },
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)
        payment.user = self.user
        payment.save()

        self.assertTrue(payment.is_installment)
        self.assertEqual(payment.installment_total, 3)
        self.assertEqual(payment.installment_number, 1)

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
    def test_credit_card_statement_form_has_processing_feedback(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:credit_card_statement_import"))

        self.assertContains(response, "data-statement-analysis-form")
        self.assertContains(response, 'role="status" aria-live="polite" hidden')
        self.assertContains(response, "Analisando fatura...")

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
        self.assertEqual(statement.due_date, date(2026, 9, 25))
        self.assertContains(response, 'name="due_date"')
        self.assertContains(response, "Mercado Central")
        self.assertContains(
            response,
            f"Total de lançamentos encontrados: <strong>{statement.items.count()}</strong>",
        )
        self.assertContains(response, "Confirmar importação")
        self.assertEqual(Payment.objects.filter(user=self.user, title="Mercado Central").count(), 0)

    @override_settings(GEMINI_API_KEY="")
    def test_identical_statement_entries_are_preserved_and_imported(self):
        self.client.force_login(self.user)
        entry = CardStatementEntry(
            title="Mercado Central",
            amount=Decimal("123.45"),
            payment_date=date(2026, 7, 10),
            raw_data={"line": "10/07 Mercado Central 123,45"},
        )
        with patch("payments.credit_card_statement_import.parse_credit_card_entries", return_value=(
            [entry, entry], CreditCardStatement.ParserSource.REGEX,
        )):
            response = self.client.post(
                reverse("payments:credit_card_statement_import"),
                {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
                HTTP_HX_REQUEST="true",
            )

        statement = CreditCardStatement.objects.get(user=self.user)
        items = list(statement.items.all())
        self.assertEqual(len(items), 2)
        self.assertNotEqual(items[0].import_hash, items[1].import_hash)
        self.assertContains(response, "Total de lançamentos encontrados: <strong>2</strong>")

        response = self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {"items": [str(item.pk) for item in items], "due_date": "2026-09-25"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(response.status_code, 204)
        self.assertEqual(Payment.objects.filter(user=self.user, credit_card_statement=statement, kind=Payment.Kind.EXPENSE).count(), 2)

    @override_settings(GEMINI_API_KEY="")
    def test_reimport_adds_a_second_identical_purchase_without_repeating_the_first(self):
        self.client.force_login(self.user)
        entry = CardStatementEntry(
            title="MERCADO EXEMPLO",
            amount=Decimal("18.00"),
            payment_date=date(2026, 8, 22),
            raw_data={},
        )
        import_url = reverse("payments:credit_card_statement_import")

        with patch("payments.credit_card_statement_import.parse_credit_card_entries", return_value=(
            [entry], CreditCardStatement.ParserSource.REGEX,
        )):
            self.client.post(
                import_url,
                {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
                HTTP_HX_REQUEST="true",
            )
        first_statement = CreditCardStatement.objects.get(user=self.user)
        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": first_statement.pk}),
            {"items": [str(item.pk) for item in first_statement.items.all()], "due_date": "2026-09-25"},
            HTTP_HX_REQUEST="true",
        )

        with patch("payments.credit_card_statement_import.parse_credit_card_entries", return_value=(
            [entry, entry], CreditCardStatement.ParserSource.REGEX,
        )):
            self.client.post(
                import_url,
                {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
                HTTP_HX_REQUEST="true",
            )
        second_statement = CreditCardStatement.objects.exclude(pk=first_statement.pk).get(user=self.user)
        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": second_statement.pk}),
            {"items": [str(item.pk) for item in second_statement.items.all()], "due_date": "2026-09-25"},
            HTTP_HX_REQUEST="true",
        )

        self.assertEqual(Payment.objects.filter(user=self.user, title="MERCADO EXEMPLO").count(), 2)
        self.assertEqual(second_statement.items.filter(status=CreditCardStatementItem.Status.SKIPPED).count(), 1)
        self.assertEqual(second_statement.items.filter(status=CreditCardStatementItem.Status.IMPORTED).count(), 1)

    @override_settings(GEMINI_API_KEY="test-key")
    def test_brazilian_invoice_keeps_identical_purchases_when_gemini_returns_only_one(self):
        text = "\n".join([
            "Despesas da fatura",
            "22 de ago. 2026 MERCADO EXEMPLO - R$ 18,00",
            "22 de ago. 2026 MERCADO EXEMPLO - R$ 18,00",
            "25 de ago. 2026 PAGAMENTO ON LINE - + R$ 500,00",
            "Total CARTÃO R$ 36,00",
        ])
        gemini_entry = CardStatementEntry(
            title="MERCADO EXEMPLO",
            amount=Decimal("18.00"),
            payment_date=date(2026, 8, 22),
            raw_data={},
        )

        with patch("payments.credit_card_statement_import.parse_entries_with_gemini", return_value=[gemini_entry]):
            entries, source = parse_credit_card_entries(text)

        self.assertEqual(source, CreditCardStatement.ParserSource.REGEX)
        self.assertEqual(len(entries), 2)
        self.assertEqual(sum((entry.amount for entry in entries), Decimal("0")), Decimal("36.00"))

    @override_settings(GEMINI_API_KEY="test-key")
    def test_brazilian_pdf_text_with_separate_columns_keeps_installments_and_duplicates(self):
        text = "\n".join([
            "Despesas da fatura",
            "22 de ago. 2026", "MERCADO EXEMPLO (Parcela 02 de 03)", "-", "R$ 18,00",
            "22 de ago. 2026", "MERCADO EXEMPLO (Parcela 02 de 03)", "-", "R$ 18,00",
            "25 de ago. 2026", "PAGAMENTO ON LINE", "-", "+ R$ 500,00",
        ])
        gemini_entry = CardStatementEntry("MERCADO EXEMPLO", Decimal("18.00"), date(2026, 8, 22), {})

        with patch("payments.credit_card_statement_import.parse_entries_with_gemini", return_value=[gemini_entry]):
            entries, source = parse_credit_card_entries(text)

        self.assertEqual(source, CreditCardStatement.ParserSource.REGEX)
        self.assertEqual(len(entries), 2)
        self.assertTrue(all("Parcela 02 de 03" in entry.title for entry in entries))

    def test_statement_due_date_is_extracted_without_using_purchase_date(self):
        text = "Resumo da fatura\nData de Vencimento\nEsta fatura vence em 25/09/2026\n"
        self.assertEqual(extract_statement_due_date(text), date(2026, 9, 25))
        self.assertIsNone(extract_statement_due_date("Compra em 18/07/2026"))

    @override_settings(GEMINI_API_KEY="")
    def test_imported_installment_uses_invoice_month_with_registered_card(self):
        from dashboard.metrics import get_dashboard_metrics

        card = CreditCard.objects.create(user=self.user, name="Cartão teste", closing_day=19, due_day=25)
        entry = CardStatementEntry(
            title="LIVRARIA EXEMPLO (Parcela 02 de 03)",
            amount=Decimal("29.85"),
            payment_date=date(2026, 7, 18),
            raw_data={},
        )
        self.client.force_login(self.user)
        with patch("payments.credit_card_statement_import.parse_credit_card_entries", return_value=(
            [entry], CreditCardStatement.ParserSource.REGEX,
        )):
            self.client.post(
                reverse("payments:credit_card_statement_import"),
                {
                    "credit_card": card.pk,
                    "statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf"),
                },
                HTTP_HX_REQUEST="true",
            )
        statement = CreditCardStatement.objects.get(user=self.user)
        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {"items": [str(item.pk) for item in statement.items.all()], "due_date": "2026-09-25"},
            HTTP_HX_REQUEST="true",
        )

        payment = Payment.objects.get(user=self.user, title=entry.title)
        self.assertEqual(payment.payment_date, date(2026, 7, 18))
        self.assertEqual(payment.statement_due_date, date(2026, 9, 25))
        self.assertEqual((payment.installment_number, payment.installment_total), (2, 3))
        self.assertTrue(payment.is_installment)
        self.assertEqual(Payment.objects.filter(user=self.user, kind=Payment.Kind.EXPENSE).count(), 1)
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 7, 1))["total"], Decimal("29.85"))
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 9, 1))["total"], 0)
        self.assertContains(self.client.get(reverse("payments:list"), {"month": "7", "year": "2026"}), entry.title)
        self.assertNotContains(self.client.get(reverse("payments:list"), {"month": "9", "year": "2026"}), entry.title)

    @override_settings(GEMINI_API_KEY="")
    def test_imported_statement_without_registered_card_uses_invoice_month(self):
        from dashboard.metrics import get_dashboard_metrics

        self.client.force_login(self.user)
        self.client.post(
            reverse("payments:credit_card_statement_import"),
            {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )
        statement = CreditCardStatement.objects.get(user=self.user)
        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {"items": [str(statement.items.first().pk)], "due_date": "2026-09-25"},
            HTTP_HX_REQUEST="true",
        )

        payment = Payment.objects.get(user=self.user, kind=Payment.Kind.EXPENSE)
        self.assertIsNone(payment.credit_card_id)
        self.assertEqual(payment.statement_due_date, date(2026, 9, 25))
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 7, 1))["total"], payment.amount)
        self.assertEqual(get_dashboard_metrics(self.user, date(2026, 9, 1))["total"], 0)

    @override_settings(GEMINI_API_KEY="")
    def test_statement_confirmation_requires_invoice_due_date(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("payments:credit_card_statement_import"),
            {"statement_file": SimpleUploadedFile("fatura.pdf", _credit_card_pdf_bytes(), content_type="application/pdf")},
            HTTP_HX_REQUEST="true",
        )
        statement = CreditCardStatement.objects.get(user=self.user)
        response = self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {"items": [str(statement.items.first().pk)], "due_date": ""},
            HTTP_HX_REQUEST="true",
        )

        self.assertContains(response, "Informe a data de vencimento desta fatura.")
        self.assertFalse(Payment.objects.filter(user=self.user).exists())

    def test_backfill_corrects_previous_statement_without_changing_purchase_date(self):
        card = CreditCard.objects.create(user=self.user, name="Cartão teste", closing_day=19, due_day=25)
        method = PaymentMethod.objects.create(name="Cartão de crédito")
        statement = CreditCardStatement.objects.create(
            user=self.user,
            credit_card=card,
            file="test-only.pdf",
            extracted_text="Resumo da fatura\nData de Vencimento\nVence em 25/09/2026",
        )
        payment = Payment.objects.create(
            user=self.user,
            title="LIVRARIA EXEMPLO (Parcela 02 de 03)",
            amount=Decimal("29.85"),
            payment_date=date(2026, 7, 18),
            credit_card=card,
            payment_method=method,
            credit_card_statement=statement,
        )
        CreditCardStatementItem.objects.create(
            statement=statement,
            payment=payment,
            title=payment.title,
            amount=payment.amount,
            payment_date=payment.payment_date,
            import_hash="backfill-test",
        )
        self.assertNotEqual(payment.statement_due_date, date(2026, 9, 25))

        migration = import_module("payments.migrations.0016_credit_card_statement_due_date")
        migration.backfill_statement_due_dates(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))

        payment.refresh_from_db()
        statement.refresh_from_db()
        self.assertEqual(statement.due_date, date(2026, 9, 25))
        self.assertEqual(payment.payment_date, date(2026, 7, 18))
        self.assertEqual(payment.statement_due_date, date(2026, 9, 25))
        self.assertEqual((payment.installment_number, payment.installment_total), (2, 3))

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
                "due_date": "2026-09-25",
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
        bill = Payment.objects.get(user=self.user, credit_card_statement=statement, kind=Payment.Kind.CREDIT_CARD_BILL)
        self.assertEqual(bill.title, "Fatura Cartão de crédito")
        self.assertEqual(bill.category.name, "Fatura de cartão de crédito")
        self.assertEqual(bill.amount, Decimal("123.45"))
        self.assertEqual(bill.payment_date, date(2026, 9, 25))
        self.assertIsNone(bill.payment_method)

        self.client.post(
            reverse("payments:credit_card_statement_confirm", kwargs={"pk": statement.pk}),
            {"due_date": "2026-09-25", "items": [str(item.pk)]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(
            Payment.objects.filter(user=self.user, credit_card_statement=statement, kind=Payment.Kind.CREDIT_CARD_BILL).count(), 1
        )

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
                "due_date": "2026-09-25",
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
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    text = "\n".join(
        [
            "Fatura de cartao de credito",
            "Data de Vencimento 25/09/2026",
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
    page.insert_textbox(pymupdf.Rect(45, 45, 550, 500), text, fontsize=11)
    data = document.tobytes()
    document.close()
    return data
