import re
import unicodedata


OUT_OF_SCOPE_MESSAGE = (
    "Eu posso ajudar apenas com informações e ações relacionadas aos seus pagamentos, "
    "gastos, metas, relatórios, faturas, extratos e lembretes dentro do Gastou Lembrou."
)

UNSAFE_MESSAGE = (
    "Não posso executar essa solicitação. Posso ajudar com seus próprios dados financeiros "
    "dentro do Gastou Lembrou, sempre respeitando sua conta logada."
)

ALLOWED_KEYWORDS = {
    "agenda",
    "agendado",
    "agendados",
    "amanha",
    "cartao",
    "categoria",
    "categorias",
    "dashboard",
    "despesa",
    "despesas",
    "extrato",
    "fatura",
    "gastei",
    "gasto",
    "gastos",
    "lembrete",
    "lembretes",
    "meta",
    "metas",
    "pagamento",
    "pagamentos",
    "parcelado",
    "parcelada",
    "parceladas",
    "parcelas",
    "pix",
    "relatorio",
    "relatorios",
    "vencem",
    "vencimento",
    "ajuda",
    "arquivo",
    "cadastro",
    "conta",
    "email",
    "excluir",
    "funciona",
    "google",
    "importar",
    "login",
    "nota fiscal",
    "privacidade",
    "redefinir",
    "senha",
    "spike",
    "suporte",
    "termos",
}

UNSAFE_PATTERNS = (
    r"\bdados?\s+de\s+outro\s+usu[aá]rio\b",
    r"\bsenha\b.*\b(banco|admin|servidor|sistema)\b",
    r"\bignore\b.*\binstru",
    r"\bdesconsidere\b.*\binstru",
    r"\btoken\b",
    r"\bsecret\b",
    r"\bapi\s*key\b",
    r"\bdelete\b.*\buser\b",
    r"\bexclu[ai]r\b.*\bconta\b",
)

QUICK_INTENTS = {
    "scheduled": {"liste os gastos agendados", "liste pagamentos agendados", "mostre os pagamentos agendados"},
    "category_ranking": {"categoria mais usada", "categoria mais utilizada", "categoria com maior gasto", "ranking de categorias"},
    "category_expenses": {"categoria"},
    "future_installments": {"mostre minhas compras parceladas futuras", "liste parcelas futuras", "lancamentos futuros"},
    "payment_methods": {"forma de pagamento mais usada", "forma de pagamento mais utilizado", "formas de pagamento mais usadas"},
    "summary": {"resuma meus gastos", "resumo dos gastos", "resumo do dashboard"},
    "goals": {"meta", "metas"},
    "system_help": {"ajuda", "cadastro", "como funciona", "importar", "login", "nota fiscal", "privacidade", "redefinir", "senha", "spike", "suporte", "termos"},
}

SYSTEM_HELP_MARKERS = {
    "aceite",
    "cadastro",
    "dados pessoais",
    "dados tratados",
    "documentacao",
    "funcionalidade",
    "funcionalidades",
    "lgpd",
    "politica de privacidade",
    "privacidade",
    "sistema",
    "termos",
}

SYSTEM_HELP_QUESTION_PATTERNS = (
    r"\b(?:como|onde)\s+(?:eu\s+)?(?:posso|faco|crio|cadastro|configuro|uso|funciona)",
    r"\b(?:eu\s+)?posso\s+(?:cadastrar|criar|alterar|editar|excluir|importar|usar|enviar|gerar|conectar)",
    r"\b(?:e|eh)\s+possivel\s+(?:cadastrar|criar|alterar|editar|excluir|importar|usar|enviar|gerar|conectar)",
    r"\b(?:quais|que)\s+dados\b",
    r"\bo\s+que\s+(?:o\s+)?(?:sistema|gastou lembrou|spike)\b",
)


def classify_message(message):
    normalized = _normalize(message)
    if not normalized:
        return "empty"
    if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in UNSAFE_PATTERNS):
        return "unsafe"
    if any(marker in normalized for marker in SYSTEM_HELP_MARKERS) or any(
        re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in SYSTEM_HELP_QUESTION_PATTERNS
    ):
        return "system_help"
    if "categoria" in normalized and any(
        marker in normalized
        for marker in {
            "mais usada",
            "mais usado",
            "mais utilizada",
            "mais utilizado",
            "mais frequente",
            "maior gasto",
            "maior valor",
            "mais gastei",
            "ranking",
            "top ",
        }
    ):
        return "category_ranking"
    if "categoria" in normalized and any(word in normalized for word in {"liste", "listar", "mostre", "mostrar", "quanto gastei"}):
        return "category_expenses"
    for intent, keywords in QUICK_INTENTS.items():
        if any(keyword in normalized for keyword in keywords):
            return intent
    if any(keyword in normalized for keyword in ALLOWED_KEYWORDS):
        return "financial_question"
    return "out_of_scope"


def is_allowed_intent(intent):
    return intent not in {"empty", "unsafe", "out_of_scope"}


def _normalize(value):
    text = " ".join(str(value or "").strip().lower().split())
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )
