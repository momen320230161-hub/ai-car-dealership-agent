"""Compatibility guard for the high-quota Gemini 3.5 Flash-Lite option."""

import pytest

from app.agent.llm import (
    AgentLLMError,
    GeminiAgentLLM,
    build_agent_llm,
    gemini_sampling_kwargs,
    gemini_understanding_schema,
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

