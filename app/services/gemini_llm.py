"""Direct Google GenAI wrapper for analysis and grounded response generation."""

import time
import re
from collections.abc import Callable

from flask import current_app
from google import genai
from google.genai import types

from app.agent.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    RESPONSE_SYSTEM_PROMPT,
    build_analysis_prompt,
    build_response_prompt,
)
from app.agent.schemas import RequestAnalysis


class GeminiLLMError(RuntimeError):
    def __init__(self, category: str, code=None):
        super().__init__(f"Gemini generation failed: {category}")
        self.category = category
        self.code = code


def _code(error):
    return getattr(error, "code", None) or getattr(error, "status_code", None)


def _category(error):
    code = _code(error)
    message = str(error).lower()
    if code == 401 or "unauthenticated" in message:
        return "authentication"
    if code == 403 or "permission_denied" in message:
        return "permission"
    if code == 429:
        return "quota/rate-limit"
    if code == 503:
        return "service-unavailable"
    if code == 504:
        return "deadline-exceeded"
    if code == 404:
        return "invalid-model"
    if code == 400:
        return "invalid-request"
    if "connection" in message or "dns" in message:
        return "network"
    return "unexpected-api-error"


def _retry_delay(error) -> float:
    """Honor Google's bounded RetryInfo hint without exposing exception details."""
    if _code(error) != 429:
        return 5.0
    details = getattr(error, "details", {})
    for item in details.get("error", {}).get("details", []) if isinstance(details, dict) else []:
        if str(item.get("@type", "")).endswith("RetryInfo"):
            match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", str(item.get("retryDelay", "")))
            if match:
                return min(float(match.group(1)) + 1.0, 30.0)
    return 5.0


class GeminiLLMService:
    def __init__(self, *, client=None, api_key=None, model=None, sleep: Callable[[float], None] = time.sleep):
        config = current_app.config
        key = api_key if api_key is not None else config["GEMINI_API_KEY"]
        if not key:
            raise RuntimeError("GEMINI_API_KEY is required")
        self.model = model or config["GEMINI_LLM_MODEL"]
        self.client = client or genai.Client(api_key=key, http_options=types.HttpOptions(timeout=120000))
        self.sleep = sleep

    def analyze_request(self, message: str, history: list[dict[str, str]]) -> RequestAnalysis:
        response = self._generate(
            build_analysis_prompt(message, history),
            types.GenerateContentConfig(
                system_instruction=ANALYSIS_SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=RequestAnalysis.model_json_schema(),
                temperature=0,
                max_output_tokens=500,
                thinking_config=types.ThinkingConfig(thinking_level="LOW"),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, RequestAnalysis):
            return parsed
        if parsed is not None:
            return RequestAnalysis.model_validate(parsed)
        return RequestAnalysis.model_validate_json(response.text)

    def generate_response(self, state: dict) -> str:
        response = self._generate(
            build_response_prompt(state),
            types.GenerateContentConfig(
                system_instruction=RESPONSE_SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=350,
                thinking_config=types.ThinkingConfig(thinking_level="LOW"),
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
        text = (getattr(response, "text", None) or "").strip()
        if not text:
            raise GeminiLLMError("empty-response")
        return text

    def _generate(self, contents, config):
        for attempt in range(2):
            try:
                return self.client.models.generate_content(model=self.model, contents=contents, config=config)
            except Exception as error:
                code = _code(error)
                if code in {429, 503, 504} and attempt == 0:
                    self.sleep(_retry_delay(error))
                    continue
                raise GeminiLLMError(_category(error), code) from error
        raise GeminiLLMError("unexpected-api-error")
