"""Gemini generation-config compatibility regressions for the Phase 4 agent."""

from app.agent.llm import gemini_sampling_kwargs


def test_gemini_3_omits_deprecated_sampling_temperature():
    assert gemini_sampling_kwargs("gemini-3.5-flash-lite", 0.1) == {}
    assert gemini_sampling_kwargs("gemini-3.6-flash", 0.1) == {}
    assert gemini_sampling_kwargs("GEMINI-3.8-FLASH", 0.7) == {}


def test_older_or_custom_model_keeps_configured_temperature():
    assert gemini_sampling_kwargs("gemini-2.5-flash", 0.2) == {"temperature": 0.2}
    assert gemini_sampling_kwargs("custom-model", 0.4) == {"temperature": 0.4}
