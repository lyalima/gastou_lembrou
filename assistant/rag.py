import hashlib
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.utils import OperationalError, ProgrammingError
from django.utils.text import slugify

from .models import AssistantKnowledgeChunk, AssistantKnowledgeDocument


STOP_WORDS = {
    "a", "ao", "aos", "as", "com", "como", "da", "das", "de", "do", "dos", "e", "em", "eu",
    "me", "meu", "minha", "no", "nos", "o", "os", "para", "por", "que", "se", "um", "uma",
}


def sync_knowledge_base(with_embeddings=False):
    source_dir = Path(settings.SPIKE_KNOWLEDGE_DIR)
    source_paths = sorted(source_dir.glob("*.md"))
    active_paths = []
    synced = 0
    skipped = 0

    for source_path in source_paths:
        text = source_path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        relative_path = source_path.relative_to(settings.BASE_DIR).as_posix()
        active_paths.append(relative_path)
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        title, version, chunks = _parse_document(text)
        document, _ = AssistantKnowledgeDocument.objects.get_or_create(
            source_path=relative_path,
            defaults={
                "slug": _unique_slug(source_path.stem),
                "title": title,
                "version": version,
                "checksum": checksum,
            },
        )
        requires_sync = document.checksum != checksum or not document.is_active or not document.chunks.exists()
        if requires_sync:
            embeddings = _embed_documents([chunk[1] for chunk in chunks]) if with_embeddings else [None] * len(chunks)
            with transaction.atomic():
                document.title = title
                document.version = version
                document.checksum = checksum
                document.is_active = True
                document.save()
                document.chunks.all().delete()
                AssistantKnowledgeChunk.objects.bulk_create(
                    [
                        AssistantKnowledgeChunk(
                            document=document,
                            heading=heading[:220],
                            content=content,
                            position=position,
                            embedding=embeddings[position],
                        )
                        for position, (heading, content) in enumerate(chunks)
                    ]
                )
            synced += 1
        elif with_embeddings and document.chunks.filter(embedding__isnull=True).exists():
            stored_chunks = list(document.chunks.order_by("position"))
            embeddings = _embed_documents([chunk.content for chunk in stored_chunks])
            for chunk, embedding in zip(stored_chunks, embeddings):
                chunk.embedding = embedding
            AssistantKnowledgeChunk.objects.bulk_update(stored_chunks, ("embedding",))
            synced += 1
        else:
            skipped += 1

    AssistantKnowledgeDocument.objects.exclude(source_path__in=active_paths).update(is_active=False)
    return {"synced": synced, "skipped": skipped, "documents": len(active_paths)}


def ensure_knowledge_base():
    try:
        if not AssistantKnowledgeDocument.objects.filter(is_active=True).exists():
            sync_knowledge_base(with_embeddings=False)
    except (OperationalError, ProgrammingError):
        return False
    return True


def retrieve_knowledge(query, top_k=None):
    if not ensure_knowledge_base():
        return []
    limit = max(1, min(int(top_k or settings.SPIKE_RAG_TOP_K), 8))
    chunks = list(
        AssistantKnowledgeChunk.objects.filter(document__is_active=True)
        .select_related("document")
        .only("heading", "content", "embedding", "document__title", "document__source_path")
    )
    query_tokens = _tokens(query)
    query_embedding = None
    if settings.SPIKE_RAG_EMBEDDINGS_ENABLED and any(chunk.embedding for chunk in chunks):
        query_embedding = _embed_query(query)

    chunk_tokens = [(_tokens(chunk.heading), _tokens(chunk.content)) for chunk in chunks]
    document_frequency = Counter(
        token
        for heading_tokens, content_tokens in chunk_tokens
        for token in (heading_tokens | content_tokens)
    )
    ranked = []
    for chunk, (heading_tokens, content_tokens) in zip(chunks, chunk_tokens):
        lexical = _lexical_score(
            query_tokens,
            heading_tokens,
            content_tokens,
            document_frequency,
            len(chunks),
        )
        vector = _cosine_similarity(query_embedding, chunk.embedding) if query_embedding and chunk.embedding else 0.0
        score = lexical + (vector * 4.0)
        if score > 0:
            ranked.append((score, chunk))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "title": chunk.document.title,
            "heading": chunk.heading,
            "content": chunk.content,
            "source": chunk.document.source_path,
            "score": round(score, 4),
        }
        for score, chunk in ranked[:limit]
    ]


def format_knowledge_context(results):
    if not results:
        return "Nenhum trecho documental relevante foi recuperado."
    sections = []
    for index, item in enumerate(results, start=1):
        label = f"{item['title']} — {item['heading']}" if item["heading"] else item["title"]
        sections.append(f"[Fonte {index}: {label}]\n{item['content']}")
    return "\n\n".join(sections)


def _parse_document(text):
    title_match = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
    version_match = re.search(r"^Versão:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else "Documento do Gastou Lembrou"
    version = version_match.group(1).strip()[:32] if version_match else "1.0"
    chunks = []
    current_heading = title
    current_lines = []

    for line in text.splitlines():
        heading_match = re.match(r"^##\s+(.+)$", line)
        if heading_match:
            _append_chunk(chunks, current_heading, current_lines)
            current_heading = heading_match.group(1).strip()
            current_lines = []
        elif not line.startswith("# ") and not line.lower().startswith("versão:"):
            current_lines.append(line)
    _append_chunk(chunks, current_heading, current_lines)
    return title, version, chunks


def _append_chunk(chunks, heading, lines):
    content = "\n".join(lines).strip()
    if not content:
        return
    paragraphs = re.split(r"\n\s*\n", content)
    buffer = ""
    for paragraph in paragraphs:
        candidate = f"{buffer}\n\n{paragraph}".strip()
        if buffer and len(candidate) > 1800:
            chunks.append((heading, buffer))
            buffer = paragraph
        else:
            buffer = candidate
    if buffer:
        chunks.append((heading, buffer))


def _unique_slug(stem):
    base = slugify(re.sub(r"^\d+[\-_]?", "", stem)) or "documento"
    candidate = base
    counter = 2
    while AssistantKnowledgeDocument.objects.filter(slug=candidate).exists():
        candidate = f"{base}-{counter}"
        counter += 1
    return candidate


def _embed_documents(texts):
    if not texts or not settings.GEMINI_API_KEY:
        return [None] * len(texts)
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.GEMINI_EMBEDDING_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
        )
        return embeddings.embed_documents(texts)
    except Exception:
        return [None] * len(texts)


def _embed_query(text):
    if not text or not settings.GEMINI_API_KEY:
        return None
    try:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.GEMINI_EMBEDDING_MODEL,
            google_api_key=settings.GEMINI_API_KEY,
        )
        return embeddings.embed_query(text)
    except Exception:
        return None


def _tokens(value):
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", str(value or "").lower())
        if not unicodedata.combining(character)
    )
    return {
        _canonical_token(token)
        for token in re.findall(r"[a-z0-9]+", normalized)
        if len(token) > 2 and token not in STOP_WORDS
    }


def _canonical_token(token):
    # A small, deterministic normalization is enough for the product glossary
    # and avoids making local RAG depend on an external NLP service.
    if len(token) > 4 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def _lexical_score(query_tokens, heading_tokens, content_tokens, document_frequency, chunk_count):
    if not query_tokens:
        return 0.0
    heading_hits = query_tokens & heading_tokens
    content_hits = query_tokens & content_tokens

    def weight(token):
        return math.log((chunk_count + 1) / (document_frequency.get(token, 0) + 1)) + 1.0

    heading_score = sum(weight(token) * 2.5 for token in heading_hits)
    content_score = sum(weight(token) for token in content_hits)
    coverage = len(heading_hits | content_hits) / len(query_tokens)
    return heading_score + content_score + (coverage * 2.0)


def _cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
