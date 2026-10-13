from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from .graph import _complete_tool_answer, _invoke_agent, _creation_tool_feedback


@override_settings(GEMINI_API_KEY="test-key")
class SpikeResponseCompletionTests(SimpleTestCase):
    def setUp(self):
        self.model = Mock()
        self.model.invoke.return_value = AIMessage(content="Compra fictícia: R$ 25,00.")
        self.final = AIMessage(content="", response_metadata={"finish_reason": "STOP"})
        self.messages = [
            HumanMessage(content="Qual foi meu último gasto?"),
            ToolMessage(content='{"titulo":"Compra fictícia","valor":"25.00"}', name="buscar_pagamentos", tool_call_id="current"),
            self.final,
        ]

    def test_empty_stop_is_completed_with_current_tool_evidence(self):
        answer = _complete_tool_answer(self.model, "Qual foi meu último gasto?", self.messages, self.final)
        self.assertIn("25,00", answer)
        self.model.invoke.assert_called_once()
        self.assertIn("Compra fictícia", self.model.invoke.call_args.args[0][1].content)

    def test_past_turn_evidence_is_not_reused(self):
        history = [HumanMessage(content="Pergunta anterior"), ToolMessage(content="Dado antigo", name="buscar_pagamentos", tool_call_id="old")]
        _complete_tool_answer(self.model, "Último gasto?", history + self.messages, self.final)
        self.assertNotIn("Dado antigo", self.model.invoke.call_args.args[0][1].content)

    def test_no_tool_evidence_or_failed_tool_does_not_trigger_generation(self):
        for evidence in [[], [ToolMessage(content="Erro interno", status="error", tool_call_id="bad")]]:
            with self.subTest(evidence=evidence):
                answer = _complete_tool_answer(self.model, "Pergunta", [self.messages[0], *evidence, self.final], self.final)
                self.assertEqual(answer, "")
        self.model.invoke.assert_not_called()

    def test_safety_block_is_not_retried(self):
        for metadata in [{"finish_reason": "SAFETY"}, {"finish_reason": "STOP", "prompt_feedback": {"block_reason": "SAFETY"}}]:
            final = AIMessage(content="", response_metadata=metadata)
            self.assertEqual(_complete_tool_answer(self.model, "Pergunta", self.messages[:-1] + [final], final), "")
        self.model.invoke.assert_not_called()

    def test_empty_completion_is_not_retried_again(self):
        self.model.invoke.return_value = AIMessage(content="")
        self.assertEqual(_complete_tool_answer(self.model, "Pergunta", self.messages, self.final), "")
        self.model.invoke.assert_called_once()

    def test_agent_execution_uses_completion_only_for_empty_answer(self):
        with patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=self.model), patch("assistant.graph.build_spike_tools", return_value=[]), patch("langchain.agents.create_agent") as create:
            create.return_value.invoke.return_value = {"messages": self.messages}
            self.assertIn("25,00", _invoke_agent(Mock(), "Pergunta", [], ""))
            self.model.invoke.assert_called_once()
            self.model.invoke.reset_mock()
            create.return_value.invoke.return_value = {"messages": [AIMessage(content="Resposta original")]}
            self.assertEqual(_invoke_agent(Mock(), "Pergunta", [], ""), "Resposta original")
            self.model.invoke.assert_not_called()

    def test_creation_tool_feedback_overrides_invented_command(self):
        evidence = ToolMessage(content='{"mensagem_usuario":"Confira os dados na janela."}', name="preparar_gasto", tool_call_id="draft")
        with patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=self.model), patch("assistant.graph.build_spike_tools", return_value=[]), patch("langchain.agents.create_agent") as create:
            create.return_value.invoke.return_value = {"messages": [HumanMessage(content="Crie um gasto"), evidence, AIMessage(content="Execute consultar_opcoes_de_cadastro()") ]}
            self.assertEqual(_invoke_agent(Mock(), "Crie um gasto", [], ""), "Confira os dados na janela.")
            self.assertEqual(create.return_value.invoke.call_count, 1)

    def test_creation_feedback_is_not_reused_from_previous_turn(self):
        evidence = ToolMessage(content='{"mensagem_usuario":"Revisão antiga"}', name="preparar_gasto", tool_call_id="old")
        self.assertEqual(_creation_tool_feedback([evidence, HumanMessage(content="Outra pergunta"), self.final]), "")

    def test_invented_commands_get_only_one_repair_attempt(self):
        with patch("langchain_google_genai.ChatGoogleGenerativeAI", return_value=self.model), patch("assistant.graph.build_spike_tools", return_value=[]), patch("langchain.agents.create_agent") as create:
            create.return_value.invoke.return_value = {"messages": [AIMessage(content="Use consultar_opcoes_de_cadastro()") ]}
            answer = _invoke_agent(Mock(), "Crie um gasto", [], "")
            self.assertEqual(create.return_value.invoke.call_count, 2)
            self.assertNotIn("consultar_opcoes", answer)
            self.assertIn("Nenhum gasto foi salvo automaticamente", answer)
