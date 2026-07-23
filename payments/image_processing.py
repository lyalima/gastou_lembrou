from pathlib import Path

from django.core.files.base import ContentFile


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
PDF_SUFFIX = ".pdf"


def process_receipt_file(uploaded_file):
    suffix = Path(uploaded_file.name).suffix.lower()
    if suffix in {PDF_SUFFIX, ".png"}:
        uploaded_file.seek(0)
        return ContentFile(uploaded_file.read(), name=Path(uploaded_file.name).name)
    return process_receipt_image(uploaded_file)


def process_receipt_image(uploaded_file):
    try:
        import cv2
        import numpy as np
    except ImportError:
        uploaded_file.seek(0)
        return ContentFile(uploaded_file.read(), name=Path(uploaded_file.name).name)

    uploaded_file.seek(0)
    data = np.frombuffer(uploaded_file.read(), np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        uploaded_file.seek(0)
        return ContentFile(uploaded_file.read(), name=Path(uploaded_file.name).name)

    should_crop_document = Path(uploaded_file.name).suffix.lower() not in {".png"}
    processed = _scan_document(image, cv2, np, should_crop_document=should_crop_document)
    success, buffer = cv2.imencode(".jpg", processed, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not success:
        uploaded_file.seek(0)
        return ContentFile(uploaded_file.read(), name=Path(uploaded_file.name).name)

    stem = Path(uploaded_file.name).stem or "nota"
    return ContentFile(buffer.tobytes(), name=f"{stem}-processada.jpg")


def _scan_document(image, cv2, np, should_crop_document=True):
    if not should_crop_document:
        return _enhance_document_image(image, cv2)

    ratio = image.shape[0] / 600.0
    resized = cv2.resize(image, (int(image.shape[1] / ratio), 600))
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edged = cv2.Canny(blurred, 50, 160)
    edged = cv2.dilate(edged, None, iterations=1)
    edged = cv2.erode(edged, None, iterations=1)

    contours, _ = cv2.findContours(edged.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:10]

    document = None
    resized_area = resized.shape[0] * resized.shape[1]
    resized_shape = resized.shape[:2]
    for contour in contours:
        if not _is_plausible_document_contour(contour, resized_area, resized_shape, cv2):
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            document = approx.reshape(4, 2) * ratio
            break

    if document is not None:
        transformed = _four_point_transform(image, document, cv2, np)
        if _is_plausible_transformed_document(transformed, image):
            image = transformed

    return _enhance_document_image(image, cv2)


def _enhance_document_image(image, cv2):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    return cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)


def _is_plausible_document_contour(contour, image_area, image_shape, cv2):
    area = cv2.contourArea(contour)
    if area < image_area * 0.18:
        return False

    x, y, width, height = cv2.boundingRect(contour)
    if width < 80 or height < 120:
        return False

    image_height, image_width = image_shape
    width_coverage = width / float(image_width)
    height_coverage = height / float(image_height)
    if width_coverage < 0.45 or height_coverage < 0.45:
        return False

    aspect_ratio = width / float(height)
    if aspect_ratio < 0.18 or aspect_ratio > 4.8:
        return False

    return True


def _is_plausible_transformed_document(transformed, original):
    height, width = transformed.shape[:2]
    original_height, original_width = original.shape[:2]
    if height < max(160, original_height * 0.28):
        return False
    if width < max(160, original_width * 0.25):
        return False

    aspect_ratio = width / float(height)
    if aspect_ratio < 0.16 or aspect_ratio > 5.5:
        return False

    return True


def _four_point_transform(image, points, cv2, np):
    rect = _order_points(points, np)
    tl, tr, br, bl = rect
    width_a = np.linalg.norm(br - bl)
    width_b = np.linalg.norm(tr - tl)
    max_width = max(int(width_a), int(width_b))
    height_a = np.linalg.norm(tr - br)
    height_b = np.linalg.norm(tl - bl)
    max_height = max(int(height_a), int(height_b))

    destination = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def _order_points(points, np):
    rect = np.zeros((4, 2), dtype="float32")
    summed = points.sum(axis=1)
    rect[0] = points[np.argmin(summed)]
    rect[2] = points[np.argmax(summed)]
    diff = np.diff(points, axis=1)
    rect[1] = points[np.argmin(diff)]
    rect[3] = points[np.argmax(diff)]
    return rect
