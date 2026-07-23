from celery import shared_task

from .emails import deserialize_attachment, send_branded_email, send_serialized_email_message


@shared_task
def send_serialized_email_message_task(payload):
    send_serialized_email_message(payload)


@shared_task
def send_branded_email_task(subject, text_body, to, from_email=None, title=None, preheader="", attachments=None, reply_to=None):
    decoded_attachments = [deserialize_attachment(attachment) for attachment in attachments or []]
    send_branded_email(
        subject,
        text_body,
        to,
        from_email=from_email,
        title=title,
        preheader=preheader,
        attachments=decoded_attachments,
        reply_to=reply_to,
    )
