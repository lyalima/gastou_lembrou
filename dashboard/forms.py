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
    alert_thresholds = forms.TypedMultipleChoiceField(
        choices=(
            ("", "Não receber avisos"),
            ("50", "50%"),
            ("75", "75%"),
            ("90", "90%"),
        ),
        coerce=lambda value: int(value) if value else None,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "goal-threshold-input"}),
        label="Avisos por email",
    )

    class Meta:
        model = MonthlySpendingGoal
        fields = ("amount", "alert_thresholds")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            active_thresholds = self.instance.active_alert_thresholds
            self.fields["alert_thresholds"].initial = active_thresholds or [""]

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

    def clean_alert_thresholds(self):
        thresholds = self.cleaned_data.get("alert_thresholds") or []
        wants_no_alerts = None in thresholds
        selected_thresholds = [threshold for threshold in thresholds if threshold]
        if wants_no_alerts and selected_thresholds:
            raise forms.ValidationError("Escolha 'Não receber avisos' ou uma ou mais porcentagens, não ambos.")
        return sorted(set(selected_thresholds))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.alert_thresholds = self.cleaned_data.get("alert_thresholds") or []
        instance.alert_threshold = instance.alert_thresholds[0] if instance.alert_thresholds else None
        if commit:
            instance.save()
            self.save_m2m()
        return instance
