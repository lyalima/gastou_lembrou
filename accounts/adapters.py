from urllib.parse import urlparse

from allauth.account.adapter import DefaultAccountAdapter
from allauth.account.adapter import context as allauth_context
from django.conf import settings

from core.emails import email_brand_context, queue_email_message


class ProjectEmailSite:
    def __init__(self):
        parsed_site_url = urlparse(settings.SITE_URL)
        self.domain = parsed_site_url.netloc or parsed_site_url.path or "gastoulembrou.com.br"
        self.name = settings.PROJECT_EMAIL_SITE_NAME

    def __str__(self):
        return self.name


class AccountAdapter(DefaultAccountAdapter):
    hidden_message_templates = {
        "account/messages/logged_in.txt",
        "account/messages/logged_out.txt",
    }

    def add_message(self, request, level, message_template=None, message_context=None, extra_tags="", message=None):
        if message_template in self.hidden_message_templates:
            return
        return super().add_message(request, level, message_template, message_context, extra_tags, message)

    def render_mail(self, template_prefix, email, context, headers=None):
        context.update(
            {
                **email_brand_context(),
                "current_site": ProjectEmailSite(),
                "site_name": settings.PROJECT_EMAIL_SITE_NAME,
            }
        )
        return super().render_mail(template_prefix, email, context, headers)

    def format_email_subject(self, subject):
        return subject.strip()

    def send_mail(self, template_prefix, email, context):
        request = allauth_context.request
        ctx = {
            "request": request,
            "email": email,
            "current_site": ProjectEmailSite(),
        }
        ctx.update(context)
        message = self.render_mail(template_prefix, email, ctx)
        queue_email_message(message)
