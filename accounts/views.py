from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView
from django.db import transaction
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import FormView, UpdateView
from allauth.account.models import EmailAddress

from .forms import AccountDeleteForm, LegalUpdateAcceptanceForm, ProfileForm
from .legal import legal_context, register_legal_acceptance


class ProfileView(LoginRequiredMixin, UpdateView):
    form_class = ProfileForm
    template_name = "accounts/profile.html"
    success_url = reverse_lazy("accounts:profile")

    def get_object(self):
        return self.request.user

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def form_valid(self, form):
        old_email = form.instance.__class__.objects.only("email").get(pk=form.instance.pk).email
        response = super().form_valid(form)
        if form.instance.email != old_email:
            form.instance.email_verified = False
            form.instance.save(update_fields=["email_verified", "updated_at"])
            EmailAddress.objects.filter(user=form.instance, email=old_email).delete()
            EmailAddress.objects.filter(user=form.instance).update(primary=False)
            email_address, _ = EmailAddress.objects.update_or_create(
                user=form.instance,
                email=form.instance.email,
                defaults={"primary": True, "verified": False},
            )
            EmailAddress.objects.filter(user=form.instance).exclude(pk=email_address.pk).update(primary=False)
            email_address.send_confirmation(self.request)
            messages.info(self.request, "Email alterado. Confirme o novo endereço para continuar.")
            logout(self.request)
            return redirect("account_email_verification_sent")
        else:
            messages.success(self.request, "Perfil atualizado.")
        return response


class AccountPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def form_valid(self, form):
        messages.success(self.request, "Senha atualizada com sucesso.")
        return super().form_valid(form)


class LegalUpdateAcceptanceView(LoginRequiredMixin, FormView):
    form_class = LegalUpdateAcceptanceForm
    template_name = "accounts/legal_acceptance_required.html"
    success_url = reverse_lazy("payments:list")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(legal_context())
        return context

    def form_valid(self, form):
        register_legal_acceptance(self.request.user, self.request, source="update")
        messages.success(self.request, "Obrigado. Seu aceite dos termos atualizados foi registrado.")
        return super().form_valid(form)


class AccountDeleteView(LoginRequiredMixin, FormView):
    form_class = AccountDeleteForm
    template_name = "accounts/account_confirm_delete.html"
    success_url = reverse_lazy("core:home")

    def form_valid(self, form):
        user = self.request.user
        receipt_files = [
            (payment.image.storage, payment.image.name)
            for payment in user.payments.exclude(image="")
            if payment.image and payment.image.name
        ]

        logout(self.request)
        with transaction.atomic():
            user.delete()
            for storage, name in receipt_files:
                transaction.on_commit(lambda storage=storage, name=name: storage.delete(name), robust=True)

        messages.success(self.request, "Sua conta e os dados associados foram excluídos permanentemente.")
        return redirect(self.success_url)
