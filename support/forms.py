from django import forms
from django.conf import settings

from core.upload_validation import validate_file_extension, validate_image_signature, validate_upload_size


ALLOWED_SCREENSHOT_CONTENT_TYPES = {"image/png", "image/jpeg", "image/jpg"}
ALLOWED_SCREENSHOT_EXTENSIONS = {"png", "jpg", "jpeg"}


class SupportForm(forms.Form):
    nome = forms.CharField(max_length=120, widget=forms.TextInput(attrs={"class": "form-input"}))
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-input", "readonly": "readonly"}))
    problema = forms.CharField(widget=forms.Textarea(attrs={"class": "form-input", "rows": 6}))
    screenshot = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-input", "accept": "image/png,image/jpeg"}),
    )

    def clean_screenshot(self):
        screenshot = self.cleaned_data.get("screenshot")
        if not screenshot:
            return screenshot
        content_type = getattr(screenshot, "content_type", "")
        validate_file_extension(screenshot, ALLOWED_SCREENSHOT_EXTENSIONS, "Envie uma imagem JPG ou PNG.")
        if content_type and content_type not in ALLOWED_SCREENSHOT_CONTENT_TYPES:
            raise forms.ValidationError("Envie uma imagem JPG ou PNG.")
        validate_upload_size(screenshot, settings.MAX_SUPPORT_SCREENSHOT_MB, "imagem")
        validate_image_signature(screenshot)
        return screenshot
