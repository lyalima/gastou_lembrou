import time

import requests
from django.conf import settings


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def generate_content(payload, attempts=3):
    response = None
    for attempt in range(attempts):
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent",
            headers={
                "x-goog-api-key": settings.GEMINI_API_KEY,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.GEMINI_TIMEOUT_SECONDS,
        )
        if response.status_code not in RETRYABLE_STATUS_CODES or attempt == attempts - 1:
            response.raise_for_status()
            return response.json()
        time.sleep(attempt + 1)

    raise requests.RequestException("O Gemini não retornou uma resposta válida.")
