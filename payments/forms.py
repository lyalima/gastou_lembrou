from decimal import Decimal, InvalidOperation

from django import forms
from django.conf import settings
from django.db.models import Q

from core.upload_validation import validate_file_extension, validate_pdf_signature, validate_receipt_signature, validate_upload_size

from .classification import normalize_text
from .image_processing import process_receipt_file
from .models import Category, Payment, PaymentMethod


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
                "accept": ".csv,.ofx,text/csv,application/x-ofx,application/ofx",
            }
        ),
        help_text="Envie um extrato em CSV ou OFX.",
    )

    def clean_statement_file(self):
        statement_file = self.cleaned_data["statement_file"]
        validate_upload_size(statement_file, settings.MAX_STATEMENT_UPLOAD_MB, "extrato")
        validate_file_extension(statement_file, {"csv", "ofx"}, "Envie um extrato em CSV ou OFX.")
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

    class Meta:
        model = Payment
        fields = ("title", "category", "kind", "description", "amount", "payment_method", "is_installment", "payment_date", "scheduled_date", "image")
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-input"}),
            "category": forms.Select(attrs={"class": "form-input"}),
            "kind": forms.Select(attrs={"class": "form-input"}),
            "description": forms.Textarea(attrs={"class": "form-input", "rows": 3}),
            "payment_method": forms.Select(attrs={"class": "form-input", "data-payment-method-select": "true"}),
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
        self.fields["payment_method"].empty_label = "Selecione uma forma de pagamento"
        self.show_installment_field = self._initial_payment_method_is_credit_card()

    def clean_kind(self):
        return self.cleaned_data.get("kind") or Payment.Kind.EXPENSE

    def clean(self):
        cleaned_data = super().clean()
        payment_method = cleaned_data.get("payment_method")
        if not self._is_credit_card_method(payment_method):
            cleaned_data["is_installment"] = False
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
        if amount <= 0:
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
        if uploaded:
            instance.image = process_receipt_file(uploaded)
        if commit:
            instance.save()
            self.save_m2m()
        return instance

    @staticmethod
    def _is_credit_card_method(payment_method):
        if not payment_method:
            return False
        name = getattr(payment_method, "name", payment_method)
        return normalize_text(name) in {"cartao de credito", "cartao credito", "credito"}

    def _initial_payment_method_is_credit_card(self):
        field_name = self.add_prefix("payment_method")
        if self.is_bound and self.data.get(field_name):
            return self._is_credit_card_method(self.fields["payment_method"].queryset.filter(pk=self.data.get(field_name)).first())
        return self._is_credit_card_method(self.initial.get("payment_method") or self.instance.payment_method)
