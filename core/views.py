from django.http import JsonResponse
from django.views.generic import TemplateView

from accounts.legal import legal_context


class HomeView(TemplateView):
    template_name = "core/home.html"


class LegalTemplateView(TemplateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(legal_context())
        return context


class TermsView(LegalTemplateView):
    template_name = "core/terms.html"


class PrivacyView(LegalTemplateView):
    template_name = "core/privacy.html"


class ManifestView(TemplateView):
    def get(self, request, *args, **kwargs):
        return JsonResponse(
            {
                "name": "Gastou, Lembrou!",
                "short_name": "Gastou Lembrou",
                "description": "Gerencie pagamentos, metas e lembretes financeiros.",
                "start_url": "/pagamentos/",
                "scope": "/",
                "display": "standalone",
                "orientation": "portrait-primary",
                "background_color": "#f3f7f5",
                "theme_color": "#0d6b5a",
                "icons": [
                    {
                        "src": "/static/img/gastou-lembrou-logo.png",
                        "sizes": "192x192",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                    {
                        "src": "/static/img/gastou-lembrou-logo.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "any maskable",
                    },
                ],
            },
            content_type="application/manifest+json",
        )


class ServiceWorkerView(TemplateView):
    template_name = "core/service-worker.js"
    content_type = "application/javascript"

    def render_to_response(self, context, **response_kwargs):
        response = super().render_to_response(context, **response_kwargs)
        response["Service-Worker-Allowed"] = "/"
        response["Cache-Control"] = "no-cache"
        return response


class OfflineView(TemplateView):
    template_name = "core/offline.html"
