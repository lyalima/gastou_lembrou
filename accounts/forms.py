from django import forms
from django.contrib.auth.forms import UserChangeForm as DjangoUserChangeForm
from django.contrib.auth.forms import UserCreationForm as DjangoUserCreationForm
from django.urls import reverse
from django.utils.safestring import mark_safe
from allauth.account.forms import ResetPasswordForm as AllauthResetPasswordForm
from allauth.account.forms import ResetPasswordKeyForm as AllauthResetPasswordKeyForm
from allauth.account.forms import SignupForm
from allauth.socialaccount.forms import SignupForm as SocialSignupForm

from .legal import register_legal_acceptance
from .models import User


class UserCreationForm(DjangoUserCreationForm):
    class Meta:
        model = User
        fields = ("email",)


class UserChangeForm(DjangoUserChangeForm):
    class Meta:
        model = User
        fields = ("email", "cpf", "telefone", "email_verified", "is_active", "is_staff")


class LegalAcceptanceMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["accept_terms"] = forms.BooleanField(
            required=True,
            label=mark_safe(
                f'Li e aceito os <a href="{reverse("core:terms")}" target="_blank" rel="noopener">Termos de Uso</a>.'
            ),
            error_messages={"required": "Você precisa aceitar os Termos de Uso para criar sua conta."},
        )
        self.fields["acknowledge_privacy"] = forms.BooleanField(
            required=True,
            label=mark_safe(
                f'Li e estou ciente da <a href="{reverse("core:privacy")}" target="_blank" rel="noopener">'
                "Política de Privacidade</a>."
            ),
            error_messages={"required": "Você precisa declarar ciência da Política de Privacidade para criar sua conta."},
        )


class AccountSignupForm(LegalAcceptanceMixin, SignupForm):
    def save(self, request):
        user = super().save(request)
        register_legal_acceptance(user, request, source="email")
        return user


class GoogleSignupForm(LegalAcceptanceMixin, SocialSignupForm):
    def save(self, request):
        user = super().save(request)
        register_legal_acceptance(user, request, source="google")
        return user


class ManualAccountResetPasswordForm(AllauthResetPasswordForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {
                "class": "form-input",
                "autocomplete": "email",
                "placeholder": "voce@email.com",
            }
        )

    def clean_email(self):
        email = super().clean_email()
        self.users = [user for user in self.users if user.has_usable_password()]
        return email

    def save(self, request, **kwargs):
        if not self.users:
            return self.cleaned_data["email"]
        return super().save(request, **kwargs)


class ManualAccountResetPasswordKeyForm(AllauthResetPasswordKeyForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["password1"].widget.attrs.update(
            {
                "class": "form-input",
                "autocomplete": "new-password",
                "placeholder": "Nova senha",
            }
        )
        self.fields["password2"].widget.attrs.update(
            {
                "class": "form-input",
                "autocomplete": "new-password",
                "placeholder": "Confirme a nova senha",
            }
        )


class LegalUpdateAcceptanceForm(forms.Form):
    accept_terms = forms.BooleanField(
        required=True,
        error_messages={"required": "Você precisa aceitar os Termos de Uso atualizados para continuar."},
    )
    acknowledge_privacy = forms.BooleanField(
        required=True,
        error_messages={"required": "Você precisa declarar ciência da Política de Privacidade atualizada para continuar."},
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["accept_terms"].label = mark_safe(
            f'Li e aceito os <a href="{reverse("core:terms")}" target="_blank" rel="noopener">Termos de Uso atualizados</a>.'
        )
        self.fields["acknowledge_privacy"].label = mark_safe(
            f'Li e estou ciente da <a href="{reverse("core:privacy")}" target="_blank" rel="noopener">'
            "Política de Privacidade atualizada</a>."
        )


class AccountDeleteForm(forms.Form):
    confirmation = forms.CharField(
        label="Digite EXCLUIR para confirmar",
        max_length=7,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "autocomplete": "off",
                "placeholder": "EXCLUIR",
            }
        ),
    )

    def clean_confirmation(self):
        confirmation = self.cleaned_data["confirmation"].strip()
        if confirmation != "EXCLUIR":
            raise forms.ValidationError('Digite exatamente "EXCLUIR" para confirmar.')
        return confirmation


class ProfileForm(forms.ModelForm):
    telefone = forms.CharField(
        required=False,
        max_length=20,
        widget=forms.TextInput(
            attrs={
                "class": "form-input",
                "placeholder": "(11) 99999-9999",
                "data-intl-phone": "true",
                "data-phone-limit": "true",
                "maxlength": "20",
            }
        ),
    )

    class Meta:
        model = User
        fields = ("email", "telefone", "cpf")
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-input"}),
            "cpf": forms.TextInput(attrs={"class": "form-input", "placeholder": "000.000.000-00", "data-cpf-mask": "true"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user", None)
        super().__init__(*args, **kwargs)
        if self.user and self.user.cpf:
            self.fields["cpf"].disabled = True
            self.fields["cpf"].help_text = "O CPF é opcional, mas uma vez cadastrado não poderá ser editado."

    def clean_email(self):
        email = self.cleaned_data["email"]
        qs = User.objects.filter(email=email)
        if self.user:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("Este email já está em uso.")
        return email

    def clean_cpf(self):
        cpf = self.cleaned_data.get("cpf")
        if self.user and self.user.cpf:
            return self.user.cpf
        return cpf
