"""Compatibility guard for the high-quota Gemini 3.5 Flash-Lite option."""

import pytest

import app.agent.llm as llm_module
from app.agent.llm import (
    AgentLLMError,
    GeminiAgentLLM,
    build_agent_llm,
    gemini_sampling_kwargs,
    gemini_understanding_schema,
)
from app.agent.schemas import RequestUnderstanding


class PassingSmokeGemini:
    """Offline fake that satisfies the required live-smoke semantics."""

    model_names: list[str] = []

    def __init__(self, *, api_key, model_name: str, temperature: float = 0.1):
        del api_key, temperature
        self.model_name = model_name
        type(self).model_names.append(model_name)

    def understand(self, message: str, *, recent_messages, preferences) -> RequestUnderstanding:
        del recent_messages, preferences
        if "بي ام" in message:
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates={"condition": "used"},
            )
        if "X6" in message:
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates={"model": "X6"},
            )
        if "الضمان" in message or "تأمين" in message:
            return RequestUnderstanding(intent="knowledge_question")
        return RequestUnderstanding(intent="general")

    def understand_with_context(
        self,
        message: str,
        *,
        recent_messages,
        preferences,
        conversation_context,
    ) -> RequestUnderstanding:
        del recent_messages, conversation_context
        if "مش فارق معايا سيدان" in message:
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates={"condition": "new"},
                dialogue_action="refine",
                preference_clears=["body_type"],
            )
        if "أي حاجة أوتوماتيك" in message:
            return RequestUnderstanding(
                intent="catalog_search",
                preference_updates={"transmission": "Automatic"},
                dialogue_action="recommend",
                preference_clears=["condition", "body_type"],
            )
        if message.strip() == "مؤمن":
            return RequestUnderstanding(
                intent="general",
                pending_field_answer="customer_name",
            )
        if "الأرخص" in message:
            return RequestUnderstanding(
                intent="car_selection",
                visible_reference_selector={
                    "field": "price_egp",
                    "operator": "min",
                },
            )
        if "تفاصيل الأوتوماتيك" in message:
            return RequestUnderstanding(
                intent="car_details",
                visible_reference_selector={
                    "field": "transmission",
                    "operator": "equals",
                    "value": "Automatic",
                },
            )
        return self.understand(
            message,
            recent_messages=[],
            preferences=preferences,
        )

    def compose_general(self, message: str, *, verified_context) -> str:
        del message, verified_context
        return "العفو، أنا تحت أمرك."


class WrongWarrantySmokeGemini(PassingSmokeGemini):
    """Fake a semantic regression while keeping the API path itself successful."""

    def understand(self, message: str, *, recent_messages, preferences) -> RequestUnderstanding:
        if "الضمان" in message:
            return RequestUnderstanding(intent="general")
        return super().understand(
            message,
            recent_messages=recent_messages,
            preferences=preferences,
        )


def test_gemini_35_flash_lite_uses_current_gemini3_adapter_path() -> None:
    provider = build_agent_llm(
        {
            "AGENT_LLM_PROVIDER": "gemini",
            "AGENT_LLM_MODEL": "gemini-3.5-flash-lite",
            "AGENT_LLM_TEMPERATURE": 0.1,
            "GEMINI_API_KEY": None,
        }
    )

    assert isinstance(provider, GeminiAgentLLM)
    assert provider.model_name == "gemini-3.5-flash-lite"
    assert gemini_sampling_kwargs(provider.model_name, provider.temperature) == {}

    schema = gemini_understanding_schema()
    assert schema["type"] == "object"
    assert "preference_updates" in schema["properties"]

    # The adapter remains network-lazy. Lack of credentials must fail only when
    # an actual model call is attempted, not while constructing the provider.
    with pytest.raises(AgentLLMError, match="credentials"):
        provider.understand(
            "عايز عربية مستعملة",
            recent_messages=[],
            preferences={},
        )


def test_build_agent_llm_defaults_to_gemini_35_flash_lite() -> None:
    provider = build_agent_llm({"AGENT_LLM_PROVIDER": "gemini", "GEMINI_API_KEY": None})
    assert isinstance(provider, GeminiAgentLLM)
    assert provider.model_name == "gemini-3.5-flash-lite"


def test_agent_llm_smoke_cli_fails_without_credentials(app) -> None:
    runner = app.test_cli_runner()
    app.config["GEMINI_API_KEY"] = None
    result = runner.invoke(args=["agent-llm-smoke"])
    assert result.exit_code != 0
    assert "GEMINI_API_KEY is not configured" in result.output


def test_agent_llm_smoke_all_scenarios_enforces_expected_semantics(app, monkeypatch) -> None:
    runner = app.test_cli_runner()
    app.config["GEMINI_API_KEY"] = "test-key"
    monkeypatch.setattr(llm_module, "GeminiAgentLLM", PassingSmokeGemini)

    result = runner.invoke(args=["agent-llm-smoke", "--all-scenarios"])

    assert result.exit_code == 0, result.output
    assert result.output.count("semantic validation: PASS") == 5
    assert result.output.count("conversational semantic validation: PASS") == 5
    assert "status: PASS" in result.output


def test_agent_llm_smoke_fails_when_a_scenario_is_semantically_wrong(app, monkeypatch) -> None:
    runner = app.test_cli_runner()
    app.config["GEMINI_API_KEY"] = "test-key"
    monkeypatch.setattr(llm_module, "GeminiAgentLLM", WrongWarrantySmokeGemini)

    result = runner.invoke(args=["agent-llm-smoke", "--all-scenarios"])

    assert result.exit_code != 0
    assert "Scenario 3 (Knowledge Routing) semantic validation failed" in result.output
    assert "intent expected 'knowledge_question', got 'general'" in result.output
    assert "status: FAIL" in result.output


def test_agent_llm_smoke_fallback_matches_new_default_model(app, monkeypatch) -> None:
    runner = app.test_cli_runner()
    app.config["GEMINI_API_KEY"] = "test-key"
    app.config.pop("AGENT_LLM_MODEL", None)
    PassingSmokeGemini.model_names.clear()
    monkeypatch.setattr(llm_module, "GeminiAgentLLM", PassingSmokeGemini)

    result = runner.invoke(args=["agent-llm-smoke"])

    assert result.exit_code == 0, result.output
    assert PassingSmokeGemini.model_names == ["gemini-3.5-flash-lite"]
    assert "model: gemini-3.5-flash-lite" in result.output
