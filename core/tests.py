from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch

from .gemini import generate_content


User = get_user_model()


class LegalPagesTests(TestCase):
    def test_terms_page_is_public_and_contains_service_rules(self):
        response = self.client.get(reverse("core:terms"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Termos de Uso e Serviço")
        self.assertContains(response, "Lembretes, relatórios e insights")
        self.assertContains(response, "16 de julho de 2026")

    def test_privacy_page_is_public_and_describes_lgpd_processing(self):
        response = self.client.get(reverse("core:privacy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Política de Privacidade")
        self.assertContains(response, "Lei Geral de Proteção de Dados")
        self.assertContains(response, "Inteligência artificial e decisões automatizadas")

    def test_home_footer_links_legal_documents(self):
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, reverse("core:terms"))
        self.assertContains(response, reverse("core:privacy"))

    def test_pwa_manifest_is_available(self):
        response = self.client.get(reverse("core:manifest"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/manifest+json")
        self.assertEqual(response.json()["display"], "standalone")
        self.assertEqual(response.json()["start_url"], "/pagamentos/")

    def test_service_worker_is_available_at_root_scope(self):
        response = self.client.get(reverse("core:service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/javascript")
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertContains(response, "networkFirstNavigation")

    def test_offline_page_is_public(self):
        response = self.client.get(reverse("core:offline"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Você está offline")

    def test_authenticated_user_can_read_legal_documents(self):
        user = User.objects.create_user(email="ana@example.com", password="pass12345", email_verified=True)
        self.client.force_login(user)

        terms_response = self.client.get(reverse("core:terms"))
        privacy_response = self.client.get(reverse("core:privacy"))

        self.assertContains(terms_response, "Termos de Uso e Serviço")
        self.assertContains(terms_response, "Aceitação e abrangência")
        self.assertContains(privacy_response, "Política de Privacidade")
        self.assertContains(privacy_response, "Direitos do titular")


class GeminiClientTests(TestCase):
    @patch("core.gemini.time.sleep")
    @patch("core.gemini.requests.post")
    def test_generate_content_retries_transient_errors(self, post, sleep):
        unavailable = Mock(status_code=503)
        success = Mock(status_code=200)
        success.json.return_value = {"candidates": []}
        post.side_effect = [unavailable, success]

        result = generate_content({"contents": []})

        self.assertEqual(result, {"candidates": []})
        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(1)
