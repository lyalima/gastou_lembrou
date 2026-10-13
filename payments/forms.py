from decimal import Decimal, InvalidOperation

from django import forms
from django.conf import settings
from django.db import transaction
from django.db.models import Q

from core.upload_validation import validate_file_extension, validate_pdf_signature, validate_receipt_signature, validate_upload_size

from .classification import normalize_text
from .image_processing import process_receipt_file
from .models import Category, CreditCard, Payment, PaymentMethod, PaymentRecurrence


class CreditCardForm(forms.ModelForm):
    class Meta:
        model = CreditCard
        fields = ("name", "description", "closing_day", "due_day")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 2}),
            "closing_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31}),
            "due_day": forms.NumberInput(attrs={"class": "form-input", "min": 1, "max": 31}),
        }


class ReceiptFileInput(forms.ClearableFileInput):
    template_name = "widgets/receipt_file_input.html"
    initial_text = "atual"
    input_text = "Alterar"
    clear_checkbox_label = "Limpar"


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description")
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        queryset = Category.objects.filter(name__iexact=name)
        if self.user:
            queryset = queryset.filter(Q(user__isnull=True) | Q(user=self.user))
        else:
            queryset = queryset.filter(user__isnull=True)
        if self.instance.pk:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Você já possui uma categoria com esse nome.")
        return name


class BankStatementImportForm(forms.Form):
    statement_file = forms.FileField(
        label="Arquivo do extrato",
        widget=forms.FileInput(
            attrs={
                "class": "form-input",
                "accept": ".csv,.ofx,.pdf,text/csv,application/x-ofx,application/ofx,application/pdf",
            }
        ),
        help_text="Envie um extrato em CSV, OFX ou PDF com texto selecionável.",
    )

    def clean_statement_file(self):
        statement_file = self.cleaned_data["statement_file"]
        validate_upload_size(statement_file, settings.MAX_STATEMENT_UPLOAD_MB, "extrato")
        suffix = validate_file_extension(statement_file, {"csv", "ofx", "pdf"}, "Envie um extrato em CSV, OFX ou PDF.")
        if suffix == "pdf":
            content_type = getattr(statement_file, "content_type", "")
            if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
                raise forms.ValidationError("Envie um extrato em PDF válido.")
            validate_pdf_signature(statement_file)
            return statement_file
        allowed_content_types = {
            "text/csv",
            "application/csv",
            "application/vnd.ms-excel",
            "application/octet-stream",
            "application/x-ofx",
            "application/ofx",
            "text/plain",
        }
        content_type = getattr(statement_file, "content_type", "")
        if content_type and content_type not in allowed_content_types:
            raise forms.ValidationError("Envie um extrato em CSV ou OFX.")
        return statement_file


class CreditCardStatementImportForm(forms.Form):
    credit_card = forms.ModelChoiceField(queryset=CreditCard.objects.none(), required=False, label="Cartão", widget=forms.Select(attrs={"class": "form-input"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["credit_card"].queryset = CreditCard.objects.filter(user=user) if user else CreditCard.objects.none()

    statement_file = forms.FileField(
        label="Arquivo da fatura",
        widget=forms.FileInput(
            attrs={
                "class": "form-input",
                "accept": "application/pdf,.pdf",
            }
        ),
        help_text="Envie a fatura do cartão em PDF.",
    )

    def clean_statement_file(self):
        statement_file = self.cleaned_data["statement_file"]
        validate_upload_size(statement_file, settings.MAX_CREDIT_CARD_STATEMENT_UPLOAD_MB, "PDF")
        validate_file_extension(statement_file, {"pdf"}, "Envie uma fatura em PDF.")
        content_type = getattr(statement_file, "content_type", "")
        if content_type and content_type not in {"application/pdf", "application/octet-stream"}:
            raise forms.ValidationError("Envie uma fatura em PDF.")
        validate_pdf_signature(statement_file)
        return statement_file


class PaymentForm(forms.ModelForm):
    is_recurring = forms.BooleanField(required=False, label="Repetir este pagamento", widget=forms.CheckboxInput(attrs={"class": "form-checkbox", "data-recurring-toggle": "true"}))
    recurrence_frequency = forms.TypedChoiceField(required=False, coerce=int, empty_value=None, choices=[("", "Selecione a frequência"), *PaymentRecurrence.FREQUENCIES], label="Frequência", widget=forms.Select(attrs={"class": "form-input"}))
    INSTALLMENT_CHOICES = [(value, f"{value} parcelas") for value in range(2, 25)]
    INSTALLMENT_NUMBER_CHOICES = [(value, f"{value}ª parcela") for value in range(1, 25)]

    amount = forms.CharField(
        label="Valor",
        widget=forms.TextInput(
            attrs={
                "class": "form-input currency-input",
                "inputmode": "numeric",
                "autocomplete": "off",
                "placeholder": "0,00",
                "data-currency-cents": "true",
            }
        ),
    )
    installment_total = forms.ChoiceField(
        label="Número de parcelas",
        choices=INSTALLMENT_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-input", "data-installment-total": "true"}),
    )
    installment_number = forms.ChoiceField(
        label="Parcela atual",
        choices=INSTALLMENT_NUMBER_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-input", "data-installment-number": "true"}),
    )

    class Meta:
        model = Payment
        fields = (
            "title",
            "category",
            "kind",
            "description",
            "amount",
            "payment_method",
            "credit_card",
            "is_installment",
            "installment_total",
            "installment_number",
            "payment_date",
            "scheduled_date",
            "image",
        )
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "kind": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
            "payment_method": forms.Select(attrs={"class": "form-input", "data-payment-method-select": "true"}),
            "credit_card": forms.Select(attrs={"class": "form-input"}),
            "is_installment": forms.CheckboxInput(attrs={"class": "form-checkbox", "data-installment-checkbox": "true"}),
            "payment_date": forms.DateInput(attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"),
            "scheduled_date": forms.DateInput(attrs={"class": "form-input", "type": "date"}, format="%Y-%m-%d"),
            "image": ReceiptFileInput(attrs={"class": "form-input", "accept": "image/png,image/jpeg,application/pdf"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(Q(user__isnull=True) | Q(user=self.user))
        self.fields["category"].required = False
        self.fields["category"].empty_label = "Selecionar automaticamente"
        self.fields["kind"].required = False
        self.fields["kind"].initial = Payment.Kind.EXPENSE
        self.fields["payment_method"].queryset = PaymentMethod.objects.all()
        self.fields["credit_card"].queryset = CreditCard.objects.filter(user=self.user)
        schedule = getattr(self.instance, "recurring_schedule", None)
        if schedule and schedule.active:
            self.initial["is_recurring"] = True
            self.initial["recurrence_frequency"] = schedule.interval_months
        self.fields["payment_method"].empty_label = "Selecione uma forma de pagamento"
        self.show_installment_field = self._initial_payment_method_is_credit_card()
        self.show_installment_options = self._initial_is_installment()
        if self.instance.pk and self.instance.installment_total:
            self.fields["installment_total"].initial = self.instance.installment_total
        if self.instance.pk and self.instance.installment_number:
            self.fields["installment_number"].initial = self.instance.installment_number

    def clean_kind(self):
        return self.cleaned_data.get("kind") or Payment.Kind.EXPENSE

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get("payment_method")
        card = cleaned_data.get("credit_card")
        if card and not self._is_credit_card_method(payment_method):
            self.add_error("credit_card", "Selecione a forma de pagamento Cartão de crédito.")
        if card and not (cleaned_data.get("payment_date") or cleaned_data.get("scheduled_date")):
            self.add_error("payment_date", "Informe a data da compra para calcular a fatura.")
        if cleaned_data.get("is_recurring"):
            if not cleaned_data.get("recurrence_frequency"):
                self.add_error("recurrence_frequency", "Selecione a frequência.")
            if not (cleaned_data.get("scheduled_date") or cleaned_data.get("payment_date")):
                self.add_error("payment_date", "Informe a data inicial da recorrência.")
            if cleaned_data.get("is_installment"):
                self.add_error("is_recurring", "Uma compra parcelada não pode ser recorrente.")
            if self.instance.recurrence_id:
                self.add_error("is_recurring", "Edite o pagamento original para configurar esta recorrência.")
            schedule = getattr(self.instance, "recurring_schedule", None)
            if schedule and (schedule.interval_months != cleaned_data.get("recurrence_frequency") or schedule.anchor_date != (cleaned_data.get("scheduled_date") or cleaned_data.get("payment_date"))):
                self.add_error("is_recurring", "Para trocar a data-base ou frequência, desative esta recorrência e crie um novo pagamento recorrente. Os lançamentos já criados são preservados.")
        if not self._is_credit_card_method(payment_method):
            cleaned_data["is_installment"] = False
            cleaned_data["installment_total"] = None
            cleaned_data["installment_number"] = None
            return cleaned_data

        if not cleaned_data.get("is_installment"):
            cleaned_data["installment_total"] = None
            cleaned_data["installment_number"] = None
            return cleaned_data

        installment_total = self._parse_installment_choice(cleaned_data.get("installment_total"))
        installment_number = self._parse_installment_choice(cleaned_data.get("installment_number"))

        if not installment_total:
            self.add_error("installment_total", "Selecione o número de parcelas.")
        if not installment_number:
            self.add_error("installment_number", "Selecione qual parcela está sendo cadastrada.")
        if installment_total and installment_number and installment_number > installment_total:
            self.add_error("installment_number", "A parcela atual não pode ser maior que o total de parcelas.")
        if not cleaned_data.get("payment_date"):
            self.add_error("payment_date", "Informe a data da parcela para gerar as demais.")

        cleaned_data["installment_total"] = installment_total
        cleaned_data["installment_number"] = installment_number
        return cleaned_data

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if isinstance(value, Decimal):
            amount = value
        else:
            normalized = str(value).replace("R$", "").replace(".", "").replace(",", ".").strip()
            try:
                amount = Decimal(normalized)
            except (InvalidOperation, ValueError):
                raise forms.ValidationError("Informe um valor válido para o pagamento.")
        if not amount.is_finite() or amount <= 0:
            raise forms.ValidationError("O valor precisa ser maior que zero.")
        return amount.quantize(Decimal("0.01"))

    def clean_image(self):
        image = self.cleaned_data.get("image")
        if image:
            validate_upload_size(image, settings.MAX_RECEIPT_UPLOAD_MB, "arquivo")
            content_type = getattr(image, "content_type", "")
            allowed_content_types = {"image/png", "image/jpeg", "image/jpg", "application/pdf"}
            validate_file_extension(image, {"png", "jpg", "jpeg", "pdf"}, "Envie uma imagem PNG/JPG ou um arquivo PDF.")
            if content_type and content_type not in allowed_content_types:
                raise forms.ValidationError("Envie uma imagem PNG/JPG ou um arquivo PDF.")
            validate_receipt_signature(image)
        return image

    def save(self, commit=True):
        instance = super().save(commit=False)
        uploaded = self.cleaned_data.get("image")
        if uploaded and "image" in self.changed_data:
            instance.image = process_receipt_file(uploaded)
        if commit:
            with transaction.atomic():
                instance.save()
                self.save_m2m()
                if self.cleaned_data.get("category") and "category" in self.changed_data:
                    from .categorization import apply_manual_category
                    apply_manual_category(instance)
        return instance

    @staticmethod
    def _is_credit_card_method(payment_method):
        if not payment_method:
            return False
        name = getattr(payment_method, "name", payment_method)
        return normalize_text(name) in {"cartao de credito", "cartao credito", "credito"}

    def _initial_payment_method_is_credit_card(self):
        field_name = self.add_prefix("payment_method")
        value = self.data.get(field_name) if self.is_bound else self.initial.get("payment_method") or self.instance.payment_method
        if value and not isinstance(value, PaymentMethod):
            try:
                value = self.fields["payment_method"].queryset.filter(pk=value).first()
            except (ValueError, TypeError):
                value = None
        return self._is_credit_card_method(value)

    def _initial_is_installment(self):
        field_name = self.add_prefix("is_installment")
        if self.is_bound:
            return field_name in self.data
        return bool(self.initial.get("is_installment") or self.instance.is_installment)

    @staticmethod
    def _parse_installment_choice(value):
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
