import json
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from dashboard.models import MonthlySpendingGoal
from payments.models import Category, Payment

from .rag import format_knowledge_context, retrieve_knowledge


def build_spike_tools(user):
    from langchain.tools import tool

    @tool
    def consultar_categorias() -> str:
        """Lista nomes das categorias globais e pessoais disponíveis ao usuário. Use antes de filtrar um tema como alimentação; não invente categorias nem associe categorias ambíguas sem confirmação."""
        names = list(_available_categories(user).order_by("name").values_list("name", flat=True)[:201])
        return _json({"categorias": names[:200], "lista_truncada": len(names) > 200})

    @tool
    def buscar_pagamentos(
        data_inicial: str = "",
        data_final: str = "",
        categoria: str = "",
        forma_pagamento: str = "",
        titulo: str = "",
        situacao: str = "todos",
        parcelado: str = "todos",
        ordenacao: str = "recentes",
        limite: int = 20,
    ) -> str:
        """Busca gastos do usuário autenticado. Datas usam AAAA-MM-DD. Categoria exige nome completo do catálogo (acentos opcionais). Situação: todos, agendados, vencidos ou futuros. Parcelado: todos, sim ou nao. Ordenação: recentes ou antigos por data do gasto; cadastrados_recentemente por cadastro; maior_valor ou menor_valor. Para último gasto, use limite=1 e limite a data final a hoje."""
        queryset = _filtered_payments(
            user,
            data_inicial=data_inicial,
            data_final=data_final,
            categoria=categoria,
            forma_pagamento=forma_pagamento,
            titulo=titulo,
            situacao=situacao,
            parcelado=parcelado,
        ).select_related("category", "payment_method")
        safe_limit = max(1, min(int(limite or 20), 40))
        total_count = queryset.count()
        ordering = {
            "antigos": ("data_consulta", "created_at", "pk"),
            "cadastrados_recentemente": ("-created_at", "-pk"),
            "maior_valor": ("-amount", "-payment_date"),
            "menor_valor": ("amount", "payment_date"),
        }.get(str(ordenacao or "recentes").lower(), ("-data_consulta", "-created_at", "-pk"))
        records = []
        for payment in queryset.order_by(*ordering)[:safe_limit]:
            records.append(
                {
                    "titulo": payment.title,
                    "valor": str(payment.amount),
                    "data_pagamento": payment.payment_date.isoformat() if payment.payment_date else None,
                    "data_agendamento": payment.scheduled_date.isoformat() if payment.scheduled_date else None,
                    "categoria": payment.category.name if payment.category_id else "Sem categoria",
                    "forma_pagamento": payment.payment_method.name if payment.payment_method_id else "Sem forma",
                    "parcela": (
                        f"{payment.installment_number}/{payment.installment_total}"
                        if payment.has_installment_info
                        else None
                    ),
                }
            )
        return _json({"quantidade_total": total_count, "resultados_exibidos": len(records), "pagamentos": records})

    @tool
    def resumir_gastos(
        data_inicial: str = "",
        data_final: str = "",
        categoria: str = "",
        forma_pagamento: str = "",
        titulo: str = "",
        situacao: str = "todos",
        parcelado: str = "todos",
    ) -> str:
        """Resume gastos do usuário com filtros opcionais e informa total, quantidade, categorias e formas de pagamento. Datas usam AAAA-MM-DD."""
        queryset = _filtered_payments(
            user,
            data_inicial=data_inicial,
            data_final=data_final,
            categoria=categoria,
            forma_pagamento=forma_pagamento,
            titulo=titulo,
            situacao=situacao,
            parcelado=parcelado,
        )
        total = queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        categories = list(
            queryset.values("category__name")
            .annotate(total=Sum("amount"), quantidade=Count("id"))
            .order_by("-total")[:10]
        )
        methods = list(
            queryset.values("payment_method__name")
            .annotate(total=Sum("amount"), quantidade=Count("id"))
            .order_by("-quantidade", "-total")[:10]
        )
        return _json(
            {
                "total": str(total),
                "quantidade": queryset.count(),
                "por_categoria": [
                    {"nome": item["category__name"] or "Sem categoria", "total": str(item["total"]), "quantidade": item["quantidade"]}
                    for item in categories
                ],
                "por_forma_pagamento": [
                    {"nome": item["payment_method__name"] or "Sem forma", "total": str(item["total"]), "quantidade": item["quantidade"]}
                    for item in methods
                ],
            }
        )

    @tool
    def evolucao_de_gastos(
        data_inicial: str = "",
        data_final: str = "",
        categoria: str = "",
        forma_pagamento: str = "",
    ) -> str:
        """Agrupa os gastos do usuário por mês para comparações e análise de evolução, com filtros opcionais. Datas usam AAAA-MM-DD."""
        queryset = _filtered_payments(
            user,
            data_inicial=data_inicial,
            data_final=data_final,
            categoria=categoria,
            forma_pagamento=forma_pagamento,
        )
        periods = (
            queryset.annotate(data_metrica=Coalesce("payment_date", "scheduled_date"))
            .annotate(mes=TruncMonth("data_metrica"))
            .values("mes")
            .annotate(total=Sum("amount"), quantidade=Count("id"))
            .order_by("mes")
        )
        return _json(
            {
                "evolucao": [
                    {"mes": item["mes"].strftime("%m/%Y"), "total": str(item["total"]), "quantidade": item["quantidade"]}
                    for item in periods
                    if item["mes"]
                ]
            }
        )

    @tool
    def analisar_ranking(
        dimensao: str,
        criterio: str = "quantidade",
        data_inicial: str = "",
        data_final: str = "",
        limite: int = 10,
    ) -> str:
        """Cria ranking dos gastos do usuário. Dimensão: categoria ou forma_pagamento. Critério: quantidade ou valor. Datas usam AAAA-MM-DD."""
        dimensions = {
            "categoria": ("category__name", "Sem categoria"),
            "forma_pagamento": ("payment_method__name", "Sem forma de pagamento"),
        }
        dimension_key = str(dimensao or "").strip().lower()
        if dimension_key not in dimensions:
            return _json({"erro": "dimensao deve ser categoria ou forma_pagamento"})
        criterion = str(criterio or "quantidade").strip().lower()
        if criterion not in {"quantidade", "valor"}:
            return _json({"erro": "criterio deve ser quantidade ou valor"})

        field, empty_label = dimensions[dimension_key]
        queryset = _filtered_payments(user, data_inicial=data_inicial, data_final=data_final)
        ordering = ("-quantidade", "-total", field) if criterion == "quantidade" else ("-total", "-quantidade", field)
        safe_limit = max(1, min(int(limite or 10), 20))
        rows = (
            queryset.values(field)
            .annotate(total=Sum("amount"), quantidade=Count("id"))
            .order_by(*ordering)[:safe_limit]
        )
        return _json(
            {
                "dimensao": dimension_key,
                "criterio": criterion,
                "ranking": [
                    {
                        "posicao": position,
                        "nome": item[field] or empty_label,
                        "quantidade": item["quantidade"],
                        "total": str(item["total"] or Decimal("0.00")),
                    }
                    for position, item in enumerate(rows, start=1)
                ],
            }
        )

    @tool
    def consultar_meta(mes: str = "") -> str:
        """Consulta a meta mensal do usuário e o progresso. O mês usa AAAA-MM; vazio significa o mês atual."""
        period = _parse_month(mes) or timezone.localdate().replace(day=1)
        goal = MonthlySpendingGoal.objects.filter(user=user, period_month=period).first()
        spent = _filtered_payments(
            user,
            data_inicial=period.isoformat(),
            data_final=_month_end(period).isoformat(),
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        if not goal:
            return _json({"mes": period.strftime("%m/%Y"), "meta_definida": False, "gasto": str(spent)})
        percent = (spent / goal.amount * Decimal("100")) if goal.amount else Decimal("0")
        return _json(
            {
                "mes": period.strftime("%m/%Y"),
                "meta_definida": True,
                "meta": str(goal.amount),
                "gasto": str(spent),
                "percentual": f"{percent:.1f}",
            }
        )

    @tool
    def consultar_ajuda_do_sistema(pergunta: str) -> str:
        """Recupera documentação confiável sobre recursos, uso, privacidade, termos, segurança e solução de problemas do Gastou Lembrou."""
        return format_knowledge_context(retrieve_knowledge(pergunta))

    return [
        consultar_categorias,
        buscar_pagamentos,
        resumir_gastos,
        evolucao_de_gastos,
        analisar_ranking,
        consultar_meta,
        consultar_ajuda_do_sistema,
    ]


def _filtered_payments(
    user,
    data_inicial="",
    data_final="",
    categoria="",
    forma_pagamento="",
    titulo="",
    situacao="todos",
    parcelado="todos",
):
    queryset = Payment.objects.filter(user=user, kind=Payment.Kind.EXPENSE).annotate(
        data_consulta=Coalesce("payment_date", "scheduled_date")
    )
    start = _parse_date(data_inicial)
    end = _parse_date(data_final)
    if start and end and start > end:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    if start:
        queryset = queryset.filter(Q(payment_date__gte=start) | Q(payment_date__isnull=True, scheduled_date__gte=start))
    if end:
        queryset = queryset.filter(Q(payment_date__lte=end) | Q(payment_date__isnull=True, scheduled_date__lte=end))
    if categoria:
        wanted = _normalized_name(categoria)
        matches = [item.pk for item in _available_categories(user) if _normalized_name(item.name) == wanted]
        queryset = queryset.filter(category_id__in=matches)
    if forma_pagamento:
        queryset = queryset.filter(payment_method__name__icontains=forma_pagamento.strip())
    if titulo:
        queryset = queryset.filter(title__icontains=titulo.strip())

    today = timezone.localdate()
    normalized_status = str(situacao or "todos").strip().lower()
    if normalized_status == "agendados":
        queryset = queryset.filter(scheduled_date__isnull=False)
    elif normalized_status == "vencidos":
        queryset = queryset.filter(scheduled_date__lt=today)
    elif normalized_status == "futuros":
        queryset = queryset.filter(Q(scheduled_date__gte=today) | Q(is_installment=True, payment_date__gt=today))

    normalized_installment = str(parcelado or "todos").strip().lower()
    if normalized_installment == "sim":
        queryset = queryset.filter(is_installment=True)
    elif normalized_installment in {"nao", "não"}:
        queryset = queryset.filter(is_installment=False)
    return queryset


def _parse_date(value):
    try:
        return date.fromisoformat(str(value)) if value else None
    except (TypeError, ValueError):
        raise ValueError("Informe uma data válida no formato AAAA-MM-DD.") from None


def _available_categories(user):
    return Category.objects.filter(Q(user=user) | Q(user__isnull=True))


def _normalized_name(value):
    return "".join(char for char in unicodedata.normalize("NFKD", str(value).strip().casefold()) if not unicodedata.combining(char))


def _parse_month(value):
    try:
        return date.fromisoformat(f"{value}-01") if value else None
    except (TypeError, ValueError):
        return None


def _month_end(period):
    next_month = (period.replace(day=28) + timedelta(days=4)).replace(day=1)
    return next_month - timedelta(days=1)


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
