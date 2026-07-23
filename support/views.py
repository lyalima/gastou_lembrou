from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import FormView

from core.emails import queue_branded_email

from .forms import SupportForm


class SupportView(LoginRequiredMixin, FormView):
    form_class = SupportForm
    template_name = "support/support.html"
    success_url = reverse_lazy("support:home")

    def get_initial(self):
        initial = super().get_initial()
        initial.update({"nome": self.request.user.email.split("@")[0], "email": self.request.user.email})
        return initial

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.request.method in {"POST", "PUT"}:
            data = kwargs["data"].copy()
            data["email"] = self.request.user.email
            kwargs["data"] = data
        return kwargs

    def form_valid(self, form):
        body_content = f'''
        Nome: {form.cleaned_data['nome']}
        Email: {form.cleaned_data['email']}
        Problema: {form.cleaned_data['problema']}
        '''

        attachments = []
        screenshot = form.cleaned_data.get("screenshot")
        if screenshot:
            attachments.append((screenshot.name, screenshot.read(), screenshot.content_type))
        queue_branded_email(
            subject=f"Suporte Gastou Lembrou - {form.cleaned_data['nome']}",
            title="Nova mensagem de suporte",
            text_body=body_content.strip(),
            to=[settings.SUPPORT_EMAIL],
            reply_to=[form.cleaned_data["email"]],
            attachments=attachments,
        )
        messages.success(self.request, "Mensagem enviada com sucesso.")
        return super().form_valid(form)
