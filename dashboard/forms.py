from decimal import Decimal, InvalidOperation

from django import forms

from .models import MonthlySpendingGoal


class MonthlySpendingGoalForm(forms.ModelForm):
    amount = forms.CharField(
        label="Valor mensal da meta",
        widget=forms.TextInput(
            attrs={
                "class": "form-input goal-currency-input",
                "inputmode": "numeric",
                "autocomplete": "off",
                "placeholder": "R$ 0,00",
                "data-currency-cents": "true",
            }
        ),
    )
    alert_threshold = forms.TypedChoiceField(
        choices=(
            ("", "Não receber avisos"),
            (50, "50%"),
            (75, "75%"),
            (90, "90%"),
        ),
        coerce=lambda value: int(value) if value else None,
        empty_value=None,
        required=False,
        widget=forms.RadioSelect(attrs={"class": "goal-threshold-input"}),
        label="Aviso por email",
    )

    class Meta:
        model = MonthlySpendingGoal
        fields = ("amount", "alert_threshold")

    def clean_amount(self):
        value = self.cleaned_data["amount"]
        if isinstance(value, Decimal):
            amount = value
        else:
            normalized = str(value).replace("R$", "").replace(".", "").replace(",", ".").strip()
            try:
                amount = Decimal(normalized)
            except (InvalidOperation, ValueError):
                raise forms.ValidationError("Informe um valor válido para a meta.")
        if amount <= 0:
            raise forms.ValidationError("A meta precisa ser maior que zero.")
        return amount.quantize(Decimal("0.01"))
