from pathlib import Path

from django import forms


PDF_SIGNATURE = b"%PDF-"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SIGNATURE = b"\xff\xd8\xff"


def validate_upload_size(uploaded_file, max_mb, label="arquivo"):
    max_bytes = max_mb * 1024 * 1024
    if uploaded_file.size > max_bytes:
        raise forms.ValidationError(f"Envie um {label} de até {max_mb} MB.")


def validate_file_extension(uploaded_file, allowed_extensions, message):
    suffix = Path(uploaded_file.name).suffix.lower().lstrip(".")
    if suffix not in allowed_extensions:
        raise forms.ValidationError(message)
    return suffix


def validate_file_signature(uploaded_file, signatures_by_extension, message):
    suffix = Path(uploaded_file.name).suffix.lower().lstrip(".")
    expected_signatures = signatures_by_extension.get(suffix)
    if not expected_signatures:
        return

    position = uploaded_file.tell() if hasattr(uploaded_file, "tell") else None
    uploaded_file.seek(0)
    header = uploaded_file.read(16)
    uploaded_file.seek(position or 0)

    if not any(header.startswith(signature) for signature in expected_signatures):
        raise forms.ValidationError(message)


def validate_pdf_signature(uploaded_file):
    validate_file_signature(uploaded_file, {"pdf": (PDF_SIGNATURE,)}, "O arquivo enviado não parece ser um PDF válido.")


def validate_image_signature(uploaded_file):
    validate_file_signature(
        uploaded_file,
        {
            "png": (PNG_SIGNATURE,),
            "jpg": (JPEG_SIGNATURE,),
            "jpeg": (JPEG_SIGNATURE,),
        },
        "A imagem enviada não parece ser um arquivo JPG ou PNG válido.",
    )


def validate_receipt_signature(uploaded_file):
    validate_file_signature(
        uploaded_file,
        {
            "pdf": (PDF_SIGNATURE,),
            "png": (PNG_SIGNATURE,),
            "jpg": (JPEG_SIGNATURE,),
            "jpeg": (JPEG_SIGNATURE,),
        },
        "O arquivo enviado não parece ser um JPG, PNG ou PDF válido.",
    )
