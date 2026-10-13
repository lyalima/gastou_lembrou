import json
import unicodedata
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from dashboard.models import MonthlySpendingGoal
from dashboard.metrics import spending_date_expression
from payments.models import Category, Payment

from .rag import format_knowledge_context, retrieve_knowledge


def build_spike_tools(user, allow_actions=False, conversation=None):
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
        """Busca gastos do usuário autenticado. Datas AAAA-MM-DD seguem o dashboard: data da compra no crédito, data prevista nos demais agendados e data de pagamento nos outros. Vencimento da fatura é informação separada, não filtro mensal. Categoria exige nome completo do catálogo (acentos opcionais). Situação: todos, agendados, vencidos ou futuros. Parcelado: todos, sim ou nao. Ordenação: recentes ou antigos por data do gasto; cadastrados_recentemente por cadastro; maior_valor ou menor_valor."""
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
                    "id": str(payment.pk),
                    "titulo": payment.title,
                    "valor": str(payment.amount),
                    "data_pagamento": payment.payment_date.isoformat() if payment.payment_date else None,
                    "vencimento_fatura": payment.statement_due_date.isoformat() if payment.statement_due_date else None,
                    "data_financeira": payment.data_consulta.isoformat() if payment.data_consulta else None,
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
        """Resume gastos usando as datas do dashboard: compra no crédito, prevista nos demais agendados ou pagamento. Datas AAAA-MM-DD. Informa total, quantidade, categorias e formas de pagamento."""
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
        """Agrupa gastos pelo mês da compra no crédito, data prevista nos demais agendados ou pagamento, como o dashboard. Datas AAAA-MM-DD."""
        queryset = _filtered_payments(
            user,
            data_inicial=data_inicial,
            data_final=data_final,
            categoria=categoria,
            forma_pagamento=forma_pagamento,
        )
        periods = (
            queryset.annotate(data_metrica=spending_date_expression())
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

    tools = [
        consultar_categorias,
        buscar_pagamentos,
        resumir_gastos,
        evolucao_de_gastos,
        analisar_ranking,
        consultar_meta,
        consultar_ajuda_do_sistema,
    ]
    if allow_actions and conversation:
        @tool
        def consultar_opcoes_de_cadastro() -> str:
            """Lista IDs e nomes de categorias, formas de pagamento e cartões disponíveis para preparar um cadastro/edição. Nunca invente IDs."""
            from payments.models import CreditCard, PaymentMethod
            return _json({"categorias": list(_available_categories(user).values("id", "name")),
                          "formas": list(PaymentMethod.objects.values("id", "name")),
                          "cartoes": list(CreditCard.objects.filter(user=user).values("id", "name"))})

        @tool
        def preparar_gasto(
            title: str, amount: str,
            description: str = "", payment_date: str = "", scheduled_date: str = "",
            category: str = "", payment_method: str = "", credit_card: str = "",
            is_installment: bool = False, installment_total: int = 0, installment_number: int = 0,
            is_recurring: bool = False, recurrence_frequency: int = 0,
        ) -> str:
            """Abre revisão de um NOVO gasto pedido pelo usuário, sem salvar. Exige título, valor e data. amount é o valor do gasto/parcela em reais com ponto decimal. payment_date: data da compra no crédito ou data do pagamento nos demais; scheduled_date: data prevista, somente se agendado. Datas AAAA-MM-DD. category, payment_method e credit_card aceitam nomes exatos informados pelo usuário ou IDs reais do catálogo; nunca invente IDs. Nomes são resolvidos pelo servidor, sem diferenciar maiúsculas ou acentos. Não invente cartão, forma ou data ausentes; pergunte se ambíguo. Parcelamento exige total e número atual, gera as demais parcelas somente após confirmação; esclareça se o valor informado é total ou por parcela. Recorrência: 1, 3, 6 ou 12 meses, apenas se solicitada. A gravação exige clique do usuário em Confirmar criação, nunca uma resposta no chat."""
            from django.core.exceptions import ValidationError
            from .actions import propose_payment
            campos = {key: value for key, value in {
                "title": title, "amount": amount, "description": description, "payment_date": payment_date,
                "scheduled_date": scheduled_date, "category": category, "payment_method": payment_method, "credit_card": credit_card,
            }.items() if value != ""}
            if is_installment:
                campos.update(is_installment=True, installment_total=installment_total, installment_number=installment_number)
            if is_recurring:
                campos.update(is_recurring=True, recurrence_frequency=recurrence_frequency)
            try:
                from payments.models import CreditCard, PaymentMethod
                for field, options, label in (
                    ("category", _available_categories(user), "categoria"),
                    ("payment_method", PaymentMethod.objects.all(), "forma de pagamento"),
                    ("credit_card", CreditCard.objects.filter(user=user), "cartão"),
                ):
                    if field in campos:
                        campos[field] = _resolve_registration_option(options, campos[field], label)
                action = propose_payment(user, conversation, "create", campos)
                return _json({"proposta": str(action.pk), "status": "aguardando confirmação no botão; nenhum pagamento foi salvo", "mensagem_usuario": "A revisão do gasto está pronta. Confira os dados na janela e escolha Confirmar criação ou Cancelar. Nenhum pagamento foi salvo ainda."})
            except ValidationError as exc:
                result = {"erro": "; ".join(exc.messages)}
                if getattr(exc, "code", None) == "registration_option":
                    result["mensagem_usuario"] = result["erro"]
                return _json(result)
        tools.extend([consultar_opcoes_de_cadastro, preparar_gasto])
    return tools


def _resolve_registration_option(queryset, value, label):
    from django.core.exceptions import ValidationError

    value = str(value).strip()
    options = list(queryset.order_by("name", "pk"))
    # Resolve only within the authorized catalog, never by an unrestricted PK lookup.
    by_id = next((item for item in options if str(item.pk) == value), None)
    if by_id:
        return str(by_id.pk)
    matches = [item for item in options if _normalized_name(item.name) == _normalized_name(value)]
    if not matches:
        wanted = _registration_name(value, label)
        matches = [item for item in options if wanted and _registration_name(item.name, label) == wanted]
    if len(matches) == 1:
        return str(matches[0].pk)
    if len(matches) > 1:
        names = ", ".join(item.name for item in matches[:20])
        raise ValidationError(f"Encontrei mais de uma opção de {label}: {names}. Qual delas você deseja usar?", code="registration_option")
    if options:
        names = ", ".join(item.name for item in options[:20])
        raise ValidationError(f"Não encontrei essa opção de {label}. As opções disponíveis incluem: {names}. Qual você deseja usar?", code="registration_option")
    raise ValidationError(f"Não há opções de {label} disponíveis para sua conta. Cadastre uma opção no sistema antes de usá-la neste gasto.", code="registration_option")


def _registration_name(value, label):
    name = " ".join(_normalized_name(value).split())
    prefixes = {
        "cartão": ("cartao de credito ", "cartao "),
        "categoria": ("categoria ",),
        "forma de pagamento": ("forma de pagamento ", "pagamento via "),
    }
    for prefix in prefixes.get(label, ()):
        if name.startswith(prefix):
            return name[len(prefix):].strip()
    return name


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
        data_consulta=spending_date_expression()
    )
    start = _parse_date(data_inicial)
    end = _parse_date(data_final)
    if start and end and start > end:
        raise ValueError("A data inicial deve ser anterior ou igual à data final.")
    if start:
        queryset = queryset.filter(data_consulta__gte=start)
    if end:
        queryset = queryset.filter(data_consulta__lte=end)
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
        queryset = queryset.filter(Q(scheduled_date__gte=today) | Q(is_installment=True, data_consulta__gt=today))

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
