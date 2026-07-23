import base64
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.templatetags.static import static
from kombu.exceptions import EncodeError, OperationalError


def absolute_static_url(path):
    static_url = static(path)
    if static_url.startswith(("http://", "https://")):
        return static_url
    asset_base_url = getattr(settings, "EMAIL_ASSET_BASE_URL", settings.SITE_URL)
    return urljoin(f"{asset_base_url.rstrip('/')}/", static_url.lstrip("/"))


def email_brand_context():
    return {
        "brand_name": settings.PROJECT_EMAIL_SITE_NAME,
        "logo_url": absolute_static_url("img/gastou-lembrou-logo.png"),
        "site_url": settings.SITE_URL.rstrip("/"),
    }


def send_branded_email(subject, text_body, to, *, from_email=None, title=None, preheader="", attachments=None, reply_to=None):
    context = {
        **email_brand_context(),
        "title": title or subject,
        "preheader": preheader,
        "body": text_body,
    }
    html_body = render_to_string("emails/message.html", context)
    message = EmailMultiAlternatives(subject, text_body, from_email, to, reply_to=reply_to)
    message.attach_alternative(html_body, "text/html")
    for attachment in attachments or []:
        message.attach(*attachment)
    message.send()
    return message


def serialize_attachment(attachment):
    filename, content, mimetype = attachment
    if isinstance(content, str):
        content = content.encode()
    return {
        "filename": filename,
        "content": base64.b64encode(content).decode("ascii"),
        "mimetype": mimetype,
    }


def deserialize_attachment(attachment):
    return (
        attachment["filename"],
        base64.b64decode(attachment["content"].encode("ascii")),
        attachment["mimetype"],
    )


def serialize_alternative(alternative):
    return {
        "content": alternative.content,
        "mimetype": alternative.mimetype,
    }


def deserialize_alternative(alternative):
    return alternative["content"], alternative["mimetype"]


def serialize_email_message(message):
    return {
        "subject": message.subject,
        "body": message.body,
        "from_email": message.from_email,
        "to": message.to,
        "cc": message.cc,
        "bcc": message.bcc,
        "reply_to": message.reply_to,
        "alternatives": [serialize_alternative(alternative) for alternative in getattr(message, "alternatives", [])],
        "attachments": [serialize_attachment(attachment) for attachment in message.attachments if isinstance(attachment, tuple)],
    }


def send_serialized_email_message(payload):
    message = EmailMultiAlternatives(
        payload["subject"],
        payload["body"],
        payload["from_email"],
        payload["to"],
        bcc=payload["bcc"],
        cc=payload["cc"],
        reply_to=payload["reply_to"],
    )
    for content, mimetype in [deserialize_alternative(alternative) for alternative in payload["alternatives"]]:
        message.attach_alternative(content, mimetype)
    for attachment in payload["attachments"]:
        message.attach(*deserialize_attachment(attachment))
    message.send()
    return message


def queue_email_message(message):
    from .tasks import send_serialized_email_message_task

    payload = serialize_email_message(message)
    try:
        send_serialized_email_message_task.delay(payload)
    except (EncodeError, OperationalError):
        send_serialized_email_message(payload)


def queue_branded_email(subject, text_body, to, *, from_email=None, title=None, preheader="", attachments=None, reply_to=None):
    from .tasks import send_branded_email_task

    serialized_attachments = [serialize_attachment(attachment) for attachment in attachments or []]
    try:
        send_branded_email_task.delay(
            subject=subject,
            text_body=text_body,
            to=to,
            from_email=from_email,
            title=title,
            preheader=preheader,
            attachments=serialized_attachments,
            reply_to=reply_to,
        )
    except (EncodeError, OperationalError):
        send_branded_email(
            subject,
            text_body,
            to,
            from_email=from_email,
            title=title,
            preheader=preheader,
            attachments=attachments,
            reply_to=reply_to,
        )
