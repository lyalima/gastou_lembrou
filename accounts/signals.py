from allauth.account.signals import email_confirmed
from django.contrib.auth import login
from django.dispatch import receiver


@receiver(email_confirmed)
def mark_user_email_verified(request, email_address, **kwargs):
    user = email_address.user
    update_fields = ["updated_at"]
    if user.email != email_address.email:
        user.email = email_address.email
        update_fields.append("email")
    if not user.email_verified:
        user.email_verified = True
        update_fields.append("email_verified")
    if len(update_fields) > 1:
        user.save(update_fields=update_fields)
    email_address.__class__.objects.filter(user=user).exclude(pk=email_address.pk).update(primary=False)
    email_address.primary = True
    email_address.verified = True
    email_address.save(update_fields=["primary", "verified"])
    email_address.__class__.objects.filter(user=user).exclude(pk=email_address.pk).delete()
    if request is not None and not request.user.is_authenticated:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
