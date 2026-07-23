import json
import re
import unicodedata

import requests
from django.conf import settings

from core.gemini import generate_content


CATEGORY_KEYWORDS = {
    "alimentacao": {"mercado", "supermercado", "feira", "padaria", "restaurante", "lanche", "comida", "delivery"},
    "moradia": {"aluguel", "condominio", "energia", "luz", "agua", "gas", "internet"},
    "transporte": {"uber", "taxi", "onibus", "metro", "combustivel", "gasolina", "estacionamento", "pedagio"},
    "saude": {"farmacia", "remedio", "medico", "consulta", "hospital", "dentista", "exame"},
    "educacao": {"curso", "faculdade", "escola", "livro", "mensalidade", "material escolar"},
    "lazer": {"cinema", "streaming", "show", "viagem", "jogo", "passeio"},
    "assinaturas": {"netflix", "spotify", "assinatura", "plano", "mensalidade"},
}


def choose_category_for_title(title, categories):
    categories = list(categories)
    if not title or not categories:
        return None

    local_match = local_category_match(title, categories)
    if local_match:
        return local_match

    if settings.GEMINI_API_KEY:
        try:
            return gemini_category_match(title, categories)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            pass

    for category in categories:
        if normalize_text(category.name) in {"outro", "outros", "diversos", "geral"}:
            return category
    return None


def local_category_match(title, categories):
    normalized_title = normalize_text(title)
    title_tokens = set(normalized_title.split())
    scored = []

    for category in categories:
        normalized_category = normalize_text(category.name)
        category_tokens = set(normalized_category.split())
        score = len(title_tokens & category_tokens) * 4

        for group, keywords in CATEGORY_KEYWORDS.items():
            category_matches_group = (
                group in normalized_category
                or normalized_category in group
                or any(keyword in normalized_category for keyword in keywords)
            )
            if category_matches_group:
                score += len(title_tokens & keywords) * 2

        if score:
            scored.append((score, category.name.casefold(), category))

    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1]))
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][2]


def gemini_category_match(title, categories):
    category_ids = [str(category.pk) for category in categories]
    schema = {
        "type": "object",
        "properties": {
            "category_id": {
                "type": "string",
                "enum": category_ids,
                "description": "ID da categoria existente que melhor representa o pagamento.",
            }
        },
        "required": ["category_id"],
    }
    payload = generate_content(
        {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Classifique um pagamento pessoal usando apenas uma das categorias fornecidas. "
                            "Considere o significado do título. Nunca crie categorias e retorne somente o ID permitido."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "payment_title": title,
                                    "categories": [
                                        {"id": str(category.pk), "name": category.name}
                                        for category in categories
                                    ],
                                },
                                ensure_ascii=False,
                            )
                        }
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        },
    )
    parts = payload["candidates"][0]["content"]["parts"]
    output_text = next(part["text"] for part in parts if part.get("text"))
    selected_id = json.loads(output_text)["category_id"]
    return next((category for category in categories if str(category.pk) == str(selected_id)), None)


def normalize_text(value):
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", without_accents.casefold()).strip()
