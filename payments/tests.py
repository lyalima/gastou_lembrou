from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from accounts.legal import PRIVACY_VERSION, TERMS_VERSION
from accounts.models import LegalAcceptance

from .forms import PaymentForm
from .image_processing import _scan_document, process_receipt_file
from .models import Category, Payment, PaymentMethod, PaymentNotification
from .tasks import send_payment_confirmation, send_payment_reminders


User = get_user_model()


class PaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.other = User.objects.create_user(email="bia@example.com", password="pass12345", email_verified=True)
        self.category = Category.objects.create(name="Mercado")
        self.other_category = Category.objects.create(name="Outro")
        self.payment_method = PaymentMethod.objects.create(name="Pix")
        for user in (self.user, self.other):
            LegalAcceptance.objects.create(
                user=user,
                terms_version=TERMS_VERSION,
                privacy_version=PRIVACY_VERSION,
                source=LegalAcceptance.Source.EMAIL,
            )

    def test_payment_list_is_scoped_to_authenticated_user(self):
        Payment.objects.create(user=self.user, category=self.category, title="Arroz", amount=Decimal("20.00"), payment_date=date(2026, 5, 1))
        Payment.objects.create(user=self.other, category=self.other_category, title="Privado", amount=Decimal("99.00"), payment_date=date(2026, 5, 2))

        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:list"))

        self.assertContains(response, "Arroz")
        self.assertNotContains(response, "Privado")

    def test_filters_by_title_category_month_year_and_order(self):
        Payment.objects.create(user=self.user, category=self.category, title="Aluguel", amount=Decimal("900.00"), payment_date=date(2026, 4, 1))
        target = Payment.objects.create(user=self.user, category=self.category, title="Feira", amount=Decimal("30.00"), payment_date=date(2026, 5, 10))

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("payments:list"),
            {"q": "Feira", "category": self.category.pk, "month": "5", "year": "2026", "order": "asc"},
        )

        self.assertEqual(list(response.context["payments"]), [target])

    def test_filters_by_exact_payment_day(self):
        target = Payment.objects.create(user=self.user, category=self.category, title="Feira", amount=Decimal("30.00"), payment_date=date(2026, 5, 10))
        Payment.objects.create(user=self.user, category=self.category, title="Mercado", amount=Decimal("40.00"), payment_date=date(2026, 5, 11))

        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:list"), {"day": "2026-05-10"})

        self.assertEqual(list(response.context["payments"]), [target])

    def test_filters_by_payment_method(self):
        card = PaymentMethod.objects.create(name="Cartao")
        Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=self.payment_method,
            title="Pix mercado",
            amount=Decimal("30.00"),
        )
        target = Payment.objects.create(
            user=self.user,
            category=self.category,
            payment_method=card,
            title="Cartao farmacia",
            amount=Decimal("40.00"),
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("payments:list"), {"payment_method": card.pk})

        self.assertContains(response, "Forma de pagamento")
        self.assertEqual(list(response.context["payments"]), [target])

    def test_filters_by_scheduled_status(self):
        scheduled = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta agendada",
            amount=Decimal("80.00"),
            scheduled_date=date(2026, 5, 30),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta sem agendamento",
            amount=Decimal("40.00"),
        )

        self.client.force_login(self.user)
        scheduled_response = self.client.get(reverse("payments:list"), {"schedule_status": "scheduled"})
        unscheduled_response = self.client.get(reverse("payments:list"), {"schedule_status": "unscheduled"})

        self.assertContains(scheduled_response, "Agendamento")
        self.assertEqual(list(scheduled_response.context["payments"]), [scheduled])
        self.assertContains(unscheduled_response, "Conta sem agendamento")
        self.assertNotContains(unscheduled_response, "Conta agendada")

    def test_pagination_preserves_active_filters(self):
        for index in range(13):
            Payment.objects.create(
                user=self.user,
                category=self.category,
                payment_method=self.payment_method,
                title=f"Mercado {index}",
                amount=Decimal("10.00"),
                payment_date=date(2026, 5, index + 1),
            )
        Payment.objects.create(
            user=self.user,
            category=self.other_category,
            title="Outro filtro",
            amount=Decimal("99.00"),
            payment_date=date(2026, 5, 20),
        )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("payments:list"),
            {"category": self.category.pk, "payment_method": self.payment_method.pk, "month": "5", "year": "2026"},
        )

        self.assertContains(
            response,
            f"?category={self.category.pk}&amp;payment_method={self.payment_method.pk}&amp;month=5&amp;year=2026&amp;page=2",
        )
        self.assertContains(response, "Última")
        self.assertContains(
            response,
            f"?category={self.category.pk}&amp;payment_method={self.payment_method.pk}&amp;month=5&amp;year=2026&amp;page=3",
        )

        second_page = self.client.get(
            reverse("payments:list"),
            {"category": self.category.pk, "payment_method": self.payment_method.pk, "month": "5", "year": "2026", "page": "2"},
        )

        self.assertContains(second_page, "Primeira")
        self.assertContains(
            second_page,
            f"?category={self.category.pk}&amp;payment_method={self.payment_method.pk}&amp;month=5&amp;year=2026&amp;page=1",
        )

    def test_payments_sidebar_link_is_active_on_payments_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:list"))

        self.assertContains(response, 'aria-label="Meus Pagamentos" aria-current="page"')

    @patch("payments.forms.process_receipt_file")
    def test_upload_is_processed_before_save(self, process_receipt_file):
        processed = SimpleUploadedFile("nota-processada.jpg", b"processed", content_type="image/jpeg")
        process_receipt_file.return_value = processed
        upload = SimpleUploadedFile("nota.jpg", _jpeg_bytes(), content_type="image/jpeg")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Nota",
                "category": self.category.pk,
                "amount": "15.50",
                "payment_date": "2026-05-20",
            },
            files={"image": upload},
        )

        self.assertTrue(form.is_valid(), form.errors)
        payment = form.save(commit=False)

        self.assertEqual(payment.image.name, "nota-processada.jpg")
        process_receipt_file.assert_called_once()

    def test_payment_form_rejects_receipt_with_invalid_content_type(self):
        upload = SimpleUploadedFile("nota.gif", b"GIF89a", content_type="image/gif")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Nota",
                "category": self.category.pk,
                "amount": "15.50",
                "payment_date": "2026-05-20",
            },
            files={"image": upload},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_payment_form_rejects_receipt_with_invalid_extension(self):
        upload = SimpleUploadedFile("nota.exe", b"%PDF-1.4", content_type="application/pdf")
        form = PaymentForm(
            user=self.user,
            data={
                "title": "Nota",
                "category": self.category.pk,
                "amount": "15.50",
                "payment_date": "2026-05-20",
            },
            files={"image": upload},
        )

        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    @override_settings(CELERY_TASK_ALWAYS_EAGER=True)
    @patch("payments.views.queue_payment_confirmation")
    def test_scheduled_payment_queues_confirmation(self, queue_payment_confirmation):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("payments:create"),
            {
                "title": "Cartão",
                "category": self.category.pk,
                "amount": "200.00",
                "scheduled_date": "2026-05-30",
            },
        )

        self.assertEqual(response.status_code, 302)
        queue_payment_confirmation.assert_called_once()

    def test_common_user_sees_category_create_button(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:list"))

        self.assertContains(response, "Nova categoria")

    def test_common_user_can_create_private_category(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:category_create"),
            {"name": "Pet", "description": "Gastos variados"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Category.objects.filter(user=self.user, name="Pet").exists())

    def test_payment_form_does_not_list_other_user_private_categories(self):
        private_category = Category.objects.create(user=self.other, name="Categoria privada")
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:create"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, private_category.name)

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

    def test_payment_update_form_preserves_date_input_values(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Internet",
            amount=Decimal("120.00"),
            payment_date=date(2026, 5, 15),
            scheduled_date=date(2026, 5, 20),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:update", kwargs={"pk": payment.pk}))

        self.assertContains(response, 'value="2026-05-15"')
        self.assertContains(response, 'value="2026-05-20"')

    def test_payment_form_lists_payment_methods(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:create"))

        self.assertContains(response, "Forma de Pagamento")
        self.assertContains(response, "Pix")

    def test_payment_can_be_created_with_payment_method(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("payments:create"),
            {
                "title": "Mercado",
                "category": self.category.pk,
                "amount": "45.90",
                "payment_method": self.payment_method.pk,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.get(title="Mercado").payment_method, self.payment_method)

    def test_scheduled_payment_sets_payment_date_when_missing(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta agendada",
            amount=Decimal("80.00"),
            scheduled_date=date(2026, 5, 30),
        )

        self.assertEqual(payment.payment_date, date(2026, 5, 30))

    def test_scheduled_payment_does_not_overwrite_existing_payment_date(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta com data diferente",
            amount=Decimal("80.00"),
            payment_date=date(2026, 5, 10),
            scheduled_date=date(2026, 5, 30),
        )

        self.assertEqual(payment.payment_date, date(2026, 5, 10))

    def test_payment_without_method_displays_dash_on_detail(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Sem forma",
            amount=Decimal("10.00"),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("payments:detail", kwargs={"pk": payment.pk}))

        self.assertContains(response, "Forma de Pagamento")
        self.assertContains(response, "<dd>-</dd>", html=True)

    def test_scheduled_payment_confirmation_is_sent_once_per_scheduled_date(self):
        payment = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Conta de luz",
            amount=Decimal("132.20"),
            scheduled_date=date(2026, 5, 31),
        )

        send_payment_confirmation(payment.pk)
        send_payment_confirmation(payment.pk)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("foi agendado para 31/05/26", mail.outbox[0].body)
        self.assertNotIn("2026-05-31", mail.outbox[0].body)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Gastou, Lembrou!", mail.outbox[0].alternatives[0][0])
        self.assertIn("/static/img/gastou-lembrou-logo.png", mail.outbox[0].alternatives[0][0])
        self.assertIn("Pagamento agendado", mail.outbox[0].alternatives[0][0])
        self.assertEqual(mail.outbox[0].attachments, [])
        self.assertEqual(
            PaymentNotification.objects.filter(
                payment=payment,
                kind=PaymentNotification.Kind.SCHEDULED_CONFIRMATION,
                scheduled_date=date(2026, 5, 31),
            ).count(),
            1,
        )

    @patch("payments.tasks.timezone.localdate", return_value=date(2026, 5, 28))
    def test_payment_reminders_are_sent_one_day_before_and_due_today_without_duplicates(self, localdate):
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Aluguel",
            amount=Decimal("900.00"),
            scheduled_date=date(2026, 5, 31),
        )
        tomorrow = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Internet",
            amount=Decimal("120.00"),
            scheduled_date=date(2026, 5, 29),
        )
        due_today = Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Cartao",
            amount=Decimal("200.00"),
            scheduled_date=date(2026, 5, 28),
        )
        Payment.objects.create(
            user=self.user,
            category=self.category,
            title="Fora do intervalo",
            amount=Decimal("40.00"),
            scheduled_date=date(2026, 5, 30),
        )

        send_payment_reminders()
        send_payment_reminders()

        self.assertEqual(len(mail.outbox), 2)
        bodies = "\n".join(message.body for message in mail.outbox)
        self.assertIn("vence amanhã", bodies)
        self.assertIn("O seu pagamento 'Cartao' vence hoje. Não esqueça de pagar!", bodies)
        self.assertEqual(mail.outbox[0].alternatives[0][1], "text/html")
        self.assertIn("Lembrete de pagamento", mail.outbox[0].alternatives[0][0])
        self.assertIn("/static/img/gastou-lembrou-logo.png", mail.outbox[0].alternatives[0][0])
        self.assertEqual(PaymentNotification.objects.filter(payment=tomorrow, kind=PaymentNotification.Kind.REMINDER_1_DAY).count(), 1)
        self.assertEqual(PaymentNotification.objects.filter(payment=due_today, kind=PaymentNotification.Kind.REMINDER_DUE_TODAY).count(), 1)


def _jpeg_bytes():
    buffer = BytesIO()
    Image.new("RGB", (10, 10), color="white").save(buffer, format="JPEG")
    return buffer.getvalue()


def _sample_pdf_bytes():
    import fitz

    document = fitz.open()
    for index in range(2):
        page = document.new_page(width=420, height=595)
        page.insert_text((45, 80), f"Conta de agua - pagina {index + 1}", fontsize=18)
        page.draw_rect(fitz.Rect(35, 45, 385, 540), color=(0, 0, 0), width=1)
    data = document.tobytes()
    document.close()
    return data


def _screenshot_png_bytes():
    import cv2
    import numpy as np

    image = np.full((408, 784, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (52, 88), (735, 128), (0, 120, 220), 2)
    cv2.rectangle(image, (52, 216), (735, 406), (0, 120, 220), 2)
    cv2.rectangle(image, (366, 146), (735, 252), (0, 120, 220), 2)
    cv2.putText(image, "DOCUMENTO AUXILIAR DA NOTA FISCAL", (190, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    cv2.putText(image, "TOTAL A PAGAR R$ 132,20", (280, 238), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    success, buffer = cv2.imencode(".png", image)
    if not success:
        raise RuntimeError("Could not create png test image")
    return buffer.tobytes()


class ReceiptImageProcessingTests(TestCase):
    def test_thin_horizontal_band_is_not_cropped_as_document(self):
        import cv2
        import numpy as np

        image = np.zeros((420, 900, 3), dtype=np.uint8)
        cv2.rectangle(image, (45, 60), (855, 115), (255, 255, 255), -1)
        cv2.putText(image, "linha da nota", (70, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

        processed = _scan_document(image, cv2, np)

        self.assertGreater(processed.shape[0], 300)

    def test_screenshot_with_internal_boxes_is_not_cropped_to_inner_section(self):
        import cv2
        import numpy as np

        image = np.full((408, 784, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (52, 88), (735, 128), (0, 120, 220), 2)
        cv2.rectangle(image, (52, 216), (735, 406), (0, 120, 220), 2)
        cv2.rectangle(image, (366, 146), (735, 252), (0, 120, 220), 2)
        cv2.putText(image, "DOCUMENTO AUXILIAR DA NOTA FISCAL", (190, 74), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
        cv2.putText(image, "TOTAL A PAGAR R$ 132,20", (280, 238), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

        processed = _scan_document(image, cv2, np)

        self.assertGreater(processed.shape[0], 350)

    def test_pdf_upload_is_saved_without_image_processing(self):
        upload = SimpleUploadedFile("conta.pdf", _sample_pdf_bytes(), content_type="application/pdf")
        original = upload.read()
        upload.seek(0)

        saved = process_receipt_file(upload)

        self.assertEqual(saved.name, "conta.pdf")
        self.assertEqual(saved.read(), original)

    def test_png_upload_is_saved_without_image_processing(self):
        upload = SimpleUploadedFile("captura.png", _screenshot_png_bytes(), content_type="image/png")
        original = upload.read()
        upload.seek(0)

        saved = process_receipt_file(upload)

        self.assertEqual(saved.name, "captura.png")
        self.assertEqual(saved.read(), original)
