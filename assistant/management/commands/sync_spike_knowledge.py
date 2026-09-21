from django.core.management.base import BaseCommand, CommandError

from assistant.rag import sync_knowledge_base


class Command(BaseCommand):
    help = "Sincroniza os documentos Markdown da base de conhecimento do Spike."

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-embeddings",
            action="store_true",
            help="Gera embeddings Gemini para recuperação semântica. Requer GEMINI_API_KEY.",
        )

    def handle(self, *args, **options):
        try:
            result = sync_knowledge_base(with_embeddings=options["with_embeddings"])
        except Exception as exc:
            raise CommandError(f"Não foi possível sincronizar a base do Spike: {exc}") from exc
        self.stdout.write(
            self.style.SUCCESS(
                f"Base sincronizada: {result['synced']} alterado(s), "
                f"{result['skipped']} inalterado(s), {result['documents']} documento(s)."
            )
        )
