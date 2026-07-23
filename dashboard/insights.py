import json
import re
from datetime import date
from decimal import Decimal

import requests
from django.conf import settings

from core.gemini import generate_content

from .metrics import get_dashboard_metrics, parse_report_month


INSIGHT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "maxLength": 240},
        "insights": {
            "type": "array",
            "minItems": 2,
            "maxItems": 4,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "maxLength": 80},
                    "body": {"type": "string", "maxLength": 260},
                    "kind": {"type": "string", "enum": ["trend", "category", "payment_method", "schedule", "general"]},
                    "priority": {"type": "string", "enum": ["positive", "info", "warning", "action"]},
                },
                "required": ["title", "body", "kind", "priority"],
            },
        },
    },
    "required": ["summary", "insights"],
}

PT_BR_CORRECTIONS = {
    "analise": "análise",
    "analises": "análises",
    "automatico": "automático",
    "automatica": "automática",
    "automaticos": "automáticos",
    "automaticas": "automáticas",
    "comparacao": "comparação",
    "comparacoes": "comparações",
    "concentracao": "concentração",
    "concentracoes": "concentrações",
    "credito": "crédito",
    "debitos": "débitos",
    "debito": "débito",
    "diminuiram": "diminuíram",
    "evolucao": "evolução",
    "ha": "há",
    "informacao": "informação",
    "informacoes": "informações",
    "media": "média",
    "mes": "mês",
    "nao": "não",
    "orientacao": "orientação",
    "padrao": "padrão",
    "padroes": "padrões",
    "periodo": "período",
    "periodos": "períodos",
    "possivel": "possível",
    "previsao": "previsão",
    "previsoes": "previsões",
    "proximo": "próximo",
    "proximos": "próximos",
    "relacao": "relação",
    "transacao": "transação",
    "transacoes": "transações",
    "uteis": "úteis",
    "variacao": "variação",
    "variacoes": "variações",
    "voce": "você",
}


def build_insight_dataset(user, period_key):
    selected_month = parse_report_month(period_key) if period_key != "all" else None
    metrics = get_dashboard_metrics(user, month=selected_month)
    comparison = _comparison_data(user, selected_month, metrics)
    return {
        "period": period_key,
        "total": float(metrics["total"]),
        "payment_count": metrics["payment_count"],
        "scheduled_count": metrics["scheduled_count"],
        "categories": [
            {"name": item["name"], "total": float(item["total"]), "count": item["count"]}
            for item in metrics["category_metrics"]
        ],
        "payment_methods": [
            {"name": item["name"], "total": float(item["total"]), "count": item["count"]}
            for item in metrics["payment_method_metrics"]
        ],
        "evolution": [
            {"period": item["name"], "total": float(item["total"]), "count": item["count"]}
            for item in metrics["month_metrics"]
        ],
        "comparison": comparison,
    }


def generate_insights(dataset):
    if not dataset["payment_count"]:
        return local_insights(dataset)
    if not settings.GEMINI_API_KEY:
        return local_insights(dataset)
    try:
        return gemini_insights(dataset)
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return local_insights(dataset)


def gemini_insights(dataset):
    payload = generate_content(
        {
            "systemInstruction": {
                "parts": [
                    {
                        "text": (
                            "Você é um analista financeiro pessoal cuidadoso. Gere insights curtos, claros e acionáveis "
                            "em português brasileiro usando somente os dados fornecidos. Escreva com ortografia, "
                            "acentuação, concordância e pontuação corretas segundo a norma-padrão brasileira. Não omita "
                            "acentos gráficos. Não invente causas, renda, metas ou previsões sem base. Não ofereça "
                            "aconselhamento financeiro profissional. Destaque comparações, concentrações de gastos, "
                            "formas de pagamento e agendamentos quando forem relevantes. Formate valores em reais com "
                            "o símbolo R$ e duas casas decimais."
                        )
                    }
                ]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(dataset, ensure_ascii=False)}],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": INSIGHT_SCHEMA,
            },
        },
    )
    content = _gemini_output_text(payload)
    result = json.loads(content)
    return normalize_insight_result({
        "source": "gemini",
        "summary": result["summary"][:240],
        "insights": result["insights"][:4],
    })


def local_insights(dataset):
    total = Decimal(str(dataset["total"]))
    insights = []
    comparison = dataset.get("comparison") or {}
    change_percent = comparison.get("change_percent")

    if dataset["payment_count"] == 0:
        return normalize_insight_result({
            "source": "local",
            "summary": "Ainda não há pagamentos suficientes neste período para gerar uma análise.",
            "insights": [
                {
                    "title": "Comece registrando seus gastos",
                    "body": "Cadastre pagamentos com categoria, data e forma de pagamento para receber comparações e padrões mais úteis.",
                    "kind": "general",
                    "priority": "info",
                }
            ],
        })

    if change_percent is not None:
        direction = "aumentaram" if change_percent > 0 else "diminuíram"
        priority = "warning" if change_percent >= 15 else "positive" if change_percent < 0 else "info"
        insights.append(
            {
                "title": "Variação em relação ao período anterior",
                "body": f"Seus gastos {direction} {abs(change_percent):.1f}% em relação ao período anterior.",
                "kind": "trend",
                "priority": priority,
            }
        )

    if dataset["categories"] and total > 0:
        top_category = max(dataset["categories"], key=lambda item: item["total"])
        share = Decimal(str(top_category["total"])) / total * 100
        insights.append(
            {
                "title": f"{top_category['name']} lidera seus gastos",
                "body": f"A categoria representa {share:.1f}% do total do período, somando {_currency(top_category['total'])}.",
                "kind": "category",
                "priority": "warning" if share >= 50 else "info",
            }
        )

    if dataset["payment_methods"] and total > 0:
        top_method = max(dataset["payment_methods"], key=lambda item: item["total"])
        share = Decimal(str(top_method["total"])) / total * 100
        insights.append(
            {
                "title": f"Maior uso: {top_method['name']}",
                "body": f"{share:.1f}% dos valores registrados foram pagos por {top_method['name']}.",
                "kind": "payment_method",
                "priority": "info",
            }
        )

    if dataset["scheduled_count"]:
        insights.append(
            {
                "title": "Pagamentos agendados sob controle",
                "body": (
                    f"Há {dataset['scheduled_count']} {pluralize_payment(dataset['scheduled_count'])} "
                    "no período. Confira os lembretes e as datas antes do vencimento."
                ),
                "kind": "schedule",
                "priority": "action",
            }
        )

    return normalize_insight_result({
        "source": "local",
        "summary": f"Foram analisados {dataset['payment_count']} pagamentos, totalizando {_currency(total)}.",
        "insights": insights[:4],
    })


def normalize_insight_result(result):
    return {
        **result,
        "summary": normalize_pt_br_text(result.get("summary", "")),
        "insights": [
            {
                **insight,
                "title": normalize_pt_br_text(insight.get("title", "")),
                "body": normalize_pt_br_text(insight.get("body", "")),
            }
            for insight in result.get("insights", [])
        ],
    }


def normalize_pt_br_text(value):
    normalized = str(value or "")
    normalized = re.sub(
        r"\b(\d+)\s+pagamento\(s\)\s+agendado\(s\)",
        lambda match: (
            f"{match.group(1)} pagamento agendado"
            if int(match.group(1)) == 1
            else f"{match.group(1)} pagamentos agendados"
        ),
        normalized,
        flags=re.IGNORECASE,
    )
    for source, target in PT_BR_CORRECTIONS.items():
        normalized = re.sub(
            rf"\b{re.escape(source)}\b",
            lambda match: _preserve_case(match.group(0), target),
            normalized,
            flags=re.IGNORECASE,
        )
    return normalized


def _preserve_case(source, target):
    if source.isupper():
        return target.upper()
    if source[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _comparison_data(user, selected_month, metrics):
    if selected_month:
        previous_month = _previous_month(selected_month)
        previous_metrics = get_dashboard_metrics(user, month=previous_month)
        return _change(metrics["total"], previous_metrics["total"], previous_month.strftime("%m/%Y"))

    evolution = metrics["month_metrics"]
    if len(evolution) < 2:
        return {}
    current = Decimal(str(evolution[-1]["total"]))
    previous = Decimal(str(evolution[-2]["total"]))
    return _change(current, previous, evolution[-2]["name"])


def _change(current, previous, reference):
    current = Decimal(current or 0)
    previous = Decimal(previous or 0)
    if previous <= 0:
        return {"previous_period": reference, "previous_total": float(previous), "change_percent": None}
    percentage = float(((current - previous) / previous) * 100)
    return {
        "previous_period": reference,
        "previous_total": float(previous),
        "change_percent": round(percentage, 1),
    }


def _previous_month(value):
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def _gemini_output_text(payload):
    candidates = payload.get("candidates") or []
    if not candidates:
        raise ValueError("A resposta do Gemini nao retornou candidatos.")
    parts = candidates[0].get("content", {}).get("parts", [])
    for part in parts:
        if part.get("text"):
            return part["text"]
    raise ValueError("A resposta do Gemini nao retornou texto.")


def _currency(value):
    amount = Decimal(value or 0)
    formatted = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def pluralize_payment(count):
    return "pagamento agendado" if count == 1 else "pagamentos agendados"
