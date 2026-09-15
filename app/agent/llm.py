"""Network-lazy LLM abstraction for structured understanding and safe composition."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from app.agent.prompts import GENERAL_COMPOSITION_SYSTEM_PROMPT, UNDERSTANDING_SYSTEM_PROMPT
from app.agent.schemas import RequestUnderstanding


class AgentLLMError(RuntimeError):
    """Controlled LLM configuration, request, or validation failure."""


class AgentLLM(Protocol):
    model_name: str

    def understand(
        self,
        message: str,
        *,
        recent_messages: Sequence[Mapping[str, Any]],
        preferences: Mapping[str, Any],
    ) -> RequestUnderstanding: ...

    def compose_general(self, message: str, *, verified_context: Mapping[str, Any]) -> str: ...


def gemini_understanding_schema() -> dict[str, Any]:
    """Keep strict Pydantic validation while omitting Gemini-unsupported keywords."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: clean(item) for key, item in value.items() if key != "additionalProperties"
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(RequestUnderstanding.model_json_schema())


def gemini_sampling_kwargs(model_name: str, temperature: float) -> dict[str, float]:
    """Use sampling controls only on model families that still support them.

    Gemini 3.x deprecated the legacy temperature/top-p/top-k sampling controls. Omitting
    temperature on that family keeps the adapter compatible with current stable Gemini 3
    endpoints while preserving the configurable value for older/custom model IDs.
    """

    if model_name.strip().casefold().startswith("gemini-3"):
        return {}
    return {"temperature": float(temperature)}


class GeminiAgentLLM:
    """Official Google Gen AI adapter; credentials are checked only on an actual call."""

    def __init__(self, *, api_key: str | None, model_name: str, temperature: float = 0.1):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = float(temperature)

    def _client(self):
        if not self.api_key:
            raise AgentLLMError("Gemini agent credentials are not configured")
        from google import genai

        return genai.Client(api_key=self.api_key)

    def understand(
        self,
        message: str,
        *,
        recent_messages: Sequence[Mapping[str, Any]],
        preferences: Mapping[str, Any],
    ) -> RequestUnderstanding:
        try:
            from google.genai import types

            payload = {
                "current_message": message,
                "current_structured_preferences": dict(preferences),
                "recent_messages_for_language_context": list(recent_messages)[-6:],
            }
            client = self._client()
            response = client.models.generate_content(
                model=self.model_name,
                contents=json.dumps(payload, ensure_ascii=False, default=str),
                config=types.GenerateContentConfig(
                    system_instruction=UNDERSTANDING_SYSTEM_PROMPT,
                    response_mime_type="application/json",
                    response_json_schema=gemini_understanding_schema(),
                    **gemini_sampling_kwargs(self.model_name, self.temperature),
                ),
            )
            if isinstance(response.parsed, RequestUnderstanding):
                return response.parsed
            if response.parsed is not None:
                return RequestUnderstanding.model_validate(response.parsed)
            if not response.text:
                raise AgentLLMError("Gemini returned no structured understanding")
            return RequestUnderstanding.model_validate_json(response.text)
        except AgentLLMError:
            raise
        except Exception as exc:
            raise AgentLLMError("Gemini request understanding failed") from exc

    def compose_general(self, message: str, *, verified_context: Mapping[str, Any]) -> str:
        try:
            from google.genai import types

            payload = {
                "customer_message": message,
                "verified_context": dict(verified_context),
            }
            client = self._client()
            response = client.models.generate_content(
                model=self.model_name,
                contents=json.dumps(payload, ensure_ascii=False, default=str),
                config=types.GenerateContentConfig(
                    system_instruction=GENERAL_COMPOSITION_SYSTEM_PROMPT,
                    max_output_tokens=180,
                    **gemini_sampling_kwargs(self.model_name, self.temperature),
                ),
            )
            text = (response.text or "").strip()
            if not text:
                raise AgentLLMError("Gemini returned no response text")
            return text
        except AgentLLMError:
            raise
        except Exception as exc:
            raise AgentLLMError("Gemini response composition failed") from exc


class DeterministicAgentLLM:
    """Offline language fixture for CI; it is never a production fallback."""

    model_name = "deterministic-agent-test-v1"

    def understand(
        self,
        message: str,
        *,
        recent_messages: Sequence[Mapping[str, Any]],
        preferences: Mapping[str, Any],
    ) -> RequestUnderstanding:
        del recent_messages, preferences
        text = " ".join(message.strip().split())
        lower = text.casefold()
        updates: dict[str, Any] = {}
        if "مستعمل" in lower or "used" in lower:
            updates["condition"] = "used"
        elif "جديد" in lower or "new" in lower:
            updates["condition"] = "new"
        if "suv" in lower:
            updates["body_type"] = "SUV"
        model_match = re.search(r"\b(x6|tiggo\s*4|s07|h6)\b", lower)
        if model_match:
            raw_model = model_match.group(1).upper()
            if raw_model == "X6":
                updates["model"] = "X6"
            elif "tiggo" in lower:
                updates["model"] = "Tiggo 4"
            elif raw_model == "S07":
                updates["model"] = "S07"
            elif raw_model == "H6":
                updates["model"] = "H6"
        budget = re.search(r"(?:تحت|أقل من|اقل من|under)\s*([0-9][0-9,]*)", lower)
        if budget:
            updates["max_price"] = float(budget.group(1).replace(",", ""))
        elif re.search(r"(?:تحت|أقل من|اقل من|under)\s+مليون", lower):
            updates["max_price"] = 1_000_000

        references: list[int] = []
        if re.search(r"(?:أول|اول|first)\s+(?:اتنين|اثنين|two)", lower):
            references = [1, 2]
        elif any(
            word in lower
            for word in ("التانية", "التانيه", "الثاني", "الثانية", "الثانيه", "second")
        ):
            references = [2]
        elif any(
            word in lower
            for word in (
                "الأولى",
                "الاولى",
                "الاول",
                "الأول",
                "الأولانية",
                "الاولانية",
                "first",
            )
        ):
            references = [1]
        elif any(
            word in lower
            for word in ("التالتة", "التالته", "الثالث", "الثالثة", "الثالثه", "third")
        ):
            references = [3]

        test_drive_language = any(
            word in lower for word in ("تست درايف", "تجربة قيادة", "test drive")
        )
        requirements_question = test_drive_language and any(
            word in lower for word in ("المطلوب", "البيانات", "متطلبات", "requirements")
        )
        if requirements_question:
            intent = "knowledge_question"
        elif (
            any(word in lower for word in ("الغاء", "إلغاء", "الغي", "ألغي", "ألغى", "cancel"))
            and test_drive_language
        ):
            intent = "cancel_test_drive"
        elif any(word in lower for word in ("المبيعات", "sales")) and any(
            word in lower
            for word in ("يكلمني", "تواصل", "اتصل", "call", "كلمنا", "تتواصل", "حد", "مندوب")
        ):
            intent = "sales_lead"
        elif test_drive_language or any(word in lower for word in ("احجز", "حجز", "book")):
            intent = "test_drive"
        elif any(word in lower for word in ("قارن", "compare")):
            intent = "car_compare"
        elif any(word in lower for word in ("اختار", "اختيار", "select", "عجبتني", "عاجباني", "حبيتها")):
            intent = "car_selection"
        elif any(
            word in lower
            for word in ("تفاصيل", "تفاصيلها", "مواصفات", "مواصفاتها", "details", "عنها")
        ):
            intent = "car_details"
        elif any(
            word in lower
            for word in (
                "ضمان",
                "تمويل",
                "تقسيط",
                "تأمين",
                "تامين",
                "السعر النهائي",
                "متاحة في المعرض",
                "سياسة",
                "warranty",
                "finance",
                "insurance",
            )
        ):
            intent = "knowledge_question"
        elif updates or any(
            word in lower
            for word in (
                "عربية",
                "سيارة",
                "وريني",
                "اعرضلي",
                "اعرض",
                "عايز",
                "معايا",
                "مليون",
                "جنيه",
                "الف",
                "ألف",
                "شيل",
                "تصفير",
                "بدون",
                "جديدة",
                "مستعملة",
                "مستعمل",
                "استعمال",
                "سيدان",
                "تاني",
                "تانيه",
                "غيرهم",
            )
        ):
            intent = "catalog_search"
        else:
            intent = "general"

        if references and not updates and intent == "general":
            intent = "car_details"

        return RequestUnderstanding(
            intent=intent,
            preference_updates=updates,
            car_reference=references[0] if len(references) == 1 else None,
            comparison_references=references if intent == "car_compare" else [],
        )

    def compose_general(self, message: str, *, verified_context: Mapping[str, Any]) -> str:
        del verified_context
        lower = message.casefold()
        if "شكر" in lower or "thank" in lower:
            return "العفو، أنا تحت أمرك في أي سؤال عن العربيات."
        if any(word in lower for word in ("اهلا", "أهلا", "مرحبا", "hello", "hi")):
            return "أهلاً بيك في AutoDrive Egypt. أقدر أساعدك تدور على عربية مناسبة."
        return "ممكن توضح لي أكتر إيه اللي محتاجه بخصوص العربية؟"


def build_agent_llm(config: Mapping[str, Any]) -> AgentLLM:
    provider = str(config.get("AGENT_LLM_PROVIDER", "gemini")).strip().lower()
    model = str(config.get("AGENT_LLM_MODEL", "gemini-3.5-flash-lite")).strip()
    temperature = float(config.get("AGENT_LLM_TEMPERATURE", 0.1))
    if provider == "gemini":
        return GeminiAgentLLM(
            api_key=config.get("GEMINI_API_KEY"),
            model_name=model,
            temperature=temperature,
        )
    if provider == "deterministic":
        return DeterministicAgentLLM()
    raise AgentLLMError(f"Unsupported agent LLM provider: {provider}")
