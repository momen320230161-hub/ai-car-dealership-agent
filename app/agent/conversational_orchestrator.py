"""Production conversational layer over the deterministic LangGraph sales orchestrator."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.agent.business_rendering import render_business_action
from app.agent.catalog_qualification import (
    explicit_brand_from_message,
    explicit_model_from_message,
    qualify_catalog_search,
)
from app.agent.graph import SalesOrchestrator
from app.agent.llm import AgentLLMError, DeterministicAgentLLM
from app.agent.rendering import render_catalog, render_error, render_knowledge
from app.agent.state import AgentState
from app.agent.turn_semantics import analyze_turn
from app.services.business_action_parsing import parse_business_fields
from app.services.catalog_preference_state_service import CatalogPreferenceStateService
from app.services.conversation_context_service import ConversationContextError
from app.services.conversational_business_action_workflow_service import (
    ConversationalBusinessActionWorkflowService,
)
from app.services.customer_memory_service import CustomerMemoryService
from app.services.recommendation_service import VisibleRecommendationError

_BUSINESS_INTENTS = {"test_drive", "cancel_test_drive", "sales_lead"}
_CATALOG_INTENTS = {"catalog_search", "car_details", "car_compare", "car_selection"}
_RESUME_TERMS = (
    "كمل الحجز",
    "نكمل الحجز",
    "كمل الطلب",
    "نكمل الطلب",
    "كمل",
    "نكمل",
    "continue",
    "resume",
)
_REQUIRED_BY_ACTION = {
    "test_drive": {"car_id", "customer_name", "phone", "preferred_date", "preferred_time"},
    "sales_lead": {"customer_name", "phone"},
    "cancel_test_drive": {"request_id"},
}
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_DEICTIC_CAR_MARKERS = (
    "العربية دي",
    "السيارة دي",
    "دي عجبتني",
    "عاجباني دي",
    "حلوة دي",
    "عايز دي",
    "عاوز دي",
    "this one",
)


class ConversationalSalesOrchestrator(SalesOrchestrator):
    """Keep deterministic execution, but make routing/memory/language conversational."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        provided_state_service = kwargs.get("state_service")
        provided_business_service = kwargs.get("business_action_service")
        super().__init__(*args, **kwargs)

        self.customer_memory = CustomerMemoryService(self.session)
        if provided_state_service is None:
            self.state_updates = CatalogPreferenceStateService(self.session)
        if provided_business_service is None:
            self.business_actions = ConversationalBusinessActionWorkflowService(
                self.session,
                customer_memory=self.customer_memory,
                recommendations=self.recommendations,
            )

    def _understand_request(self, state: AgentState) -> AgentState:
        """Augment LLM understanding with deterministic conversational state operations."""
        update = super()._understand_request(state)
        if "understanding_failed" in update.get("errors", []):
            return update

        message = state.get("normalized_message", "")
        extracted = dict(update.get("extracted_preferences") or {})

        # Common shorthand such as "عندك 320" should be treated as a model request
        # when a brand is already in focus. Entity validation still happens against DB data.
        if not extracted.get("model") and state.get("preferences", {}).get("brand"):
            token = self._catalog_model_token(message)
            if token is not None:
                extracted["model"] = token
                update["intent"] = "catalog_search"

        semantics = analyze_turn(message, state.get("preferences", {}), extracted)
        semantics_data = semantics.as_dict()

        if semantics.budget_change_unspecified:
            update["intent"] = "general"
            extracted = {}
        else:
            forced = set(semantics.force_clear_fields)
            for field in semantics.clear_fields:
                if field in forced or field not in extracted:
                    extracted[field] = None
            if semantics.force_catalog_search and update.get("intent") == "general":
                update["intent"] = "catalog_search"

        resolved_reference = self._resolve_visible_reference(
            state,
            message,
            intent=str(update.get("intent") or "general"),
        )
        if resolved_reference is not None:
            update["car_reference"] = resolved_reference
            semantics_data["resolved_visible_reference"] = resolved_reference
            semantics_data["mode"] = "reference"
            # A visible-list reference is not a new catalog filter. Prevent brand/model
            # words inside "عايز الرينو" from invalidating the very list being referenced.
            if update.get("intent") in {"car_selection", "car_details", "test_drive"}:
                extracted.pop("brand", None)
                extracted.pop("model", None)

        update["extracted_preferences"] = extracted
        update["turn_semantics"] = semantics_data
        return update

    def _route_request(self, state: AgentState) -> AgentState:
        """Allow side questions while a pending action stays safely persisted."""
        update = self._trace(state, "route_request")
        intent = state.get("intent", "general")
        pending = state.get("pending_action")
        pending_type = str((pending or {}).get("type") or "")
        has_pending_business = pending_type in _BUSINESS_INTENTS

        if "understanding_failed" in state.get("errors", []) or "state_update_failed" in state.get(
            "errors", []
        ):
            route = "general_node"
        elif intent in _BUSINESS_INTENTS:
            route = "business_gate"
        elif has_pending_business and self._continues_pending_action(state, pending_type):
            route = "business_gate"
        elif intent in _CATALOG_INTENTS:
            route = "catalog_node"
        elif intent == "knowledge_question":
            route = "rag_node"
        else:
            route = "general_node"

        update["route"] = route.removesuffix("_node")
        update["selected_route"] = route
        return update

    def _continues_pending_action(self, state: AgentState, pending_type: str) -> bool:
        message = state.get("normalized_message", "")
        intent = state.get("intent", "general")
        pending = state.get("pending_action") or {}
        fields = dict(pending.get("fields") or {})
        required = _REQUIRED_BY_ACTION.get(pending_type, set())
        missing = {name for name in required if fields.get(name) in (None, "")}

        allow_bare_name = intent == "general" and "customer_name" in missing
        parsed = parse_business_fields(message, allow_bare_name=allow_bare_name)
        explicit = set(parsed.as_json_fields())
        if explicit & required:
            return True

        text = message.casefold()
        return intent == "general" and any(term in text for term in _RESUME_TERMS)

    def _catalog_node(self, state: AgentState) -> AgentState:
        """Use flexible search semantics while preserving deterministic catalog truth."""
        intent = state.get("intent", "catalog_search")
        if intent == "car_selection" and state.get("car_reference") is None:
            selected_car_id = state.get("selected_car_id")
            if selected_car_id is not None:
                update = self._trace(state, "catalog_node")
                details = self.catalog.get_car_details(selected_car_id)
                if details is not None:
                    update["catalog_result"] = {"type": "selection", "car": details}
                    return update
        if intent != "catalog_search":
            return super()._catalog_node(state)

        update = self._trace(state, "catalog_node")
        try:
            session_id = uuid.UUID(state["session_id"])
            semantics = dict(state.get("turn_semantics") or {})
            preferences = dict(state.get("preferences") or {})

            canonical_model = self._resolve_catalog_model(
                str(preferences.get("brand") or "").strip() or None,
                str(preferences.get("model") or "").strip() or None,
            )
            if canonical_model and canonical_model != preferences.get("model"):
                self.state_updates.update_preferences(session_id, {"model": canonical_model})
                context = self.context.load(session_id)
                update.update(self._context_update(context))
                preferences = dict(context.preferences)

            pagination = bool(
                semantics.get("pagination_requested") or semantics.get("more_results_question")
            )
            qualification = qualify_catalog_search(
                preferences,
                state.get("normalized_message", ""),
            )
            if (
                not qualification.ready
                and not pagination
                and not semantics.get("force_catalog_search")
            ):
                update["catalog_result"] = {
                    "type": "clarification",
                    "message": qualification.message,
                    "missing": list(qualification.missing),
                }
                return update

            snapshot = None
            chosen_soft_condition = None
            soft_conditions = [
                str(value) for value in semantics.get("soft_condition_order", []) if value
            ]

            if pagination:
                seen_ids = self.recommendations.get_seen_car_ids(session_id)
                cars = self.catalog.recommend(
                    preferences,
                    limit=self.recommendation_limit,
                    exclude_car_ids=seen_ids,
                )
                if not cars:
                    update["catalog_result"] = {
                        "type": "clarification",
                        "message": (
                            "دول كل العربيات المطابقة للشروط الحالية حسب الكتالوج المسجل. "
                            "لو تحب نقدر نوسع شرط السعر أو النوع أو الحالة."
                        ),
                    }
                    return update
                snapshot = self.recommendations.create_visible_snapshot(
                    session_id,
                    cars,
                    preferences,
                )
            elif soft_conditions:
                base_preferences = dict(preferences)
                base_preferences.pop("condition", None)
                for condition in soft_conditions:
                    trial = dict(base_preferences)
                    trial["condition"] = condition
                    cars = self.catalog.recommend(trial, limit=self.recommendation_limit)
                    if cars:
                        snapshot = self.recommendations.create_visible_snapshot(
                            session_id,
                            cars,
                            trial,
                        )
                        chosen_soft_condition = condition
                        break
            else:
                snapshot = self.recommendations.recommend_and_snapshot(
                    session_id,
                    preferences,
                    limit=self.recommendation_limit,
                )

            if snapshot is None:
                relaxed = self.catalog.recommend_with_relaxation(
                    preferences,
                    limit=self.recommendation_limit,
                )
                if relaxed["type"] == "price_relaxation":
                    cars = relaxed["cars"]
                    snapshot = self.recommendations.create_visible_snapshot(
                        session_id,
                        cars,
                        preferences,
                    )
                    context = self.context.load(session_id)
                    update.update(self._context_update(context))
                    update["catalog_result"] = {
                        "type": "relaxed_suggestion",
                        "reason": "price",
                        "cars": [self.catalog.serialize_details(car) for car in cars],
                        "original_max_price": relaxed["original_max_price"],
                        "cheapest_price": relaxed["cheapest_price"],
                        "snapshot_id": snapshot.id,
                    }
                    return update
                if relaxed["type"] == "condition_relaxation":
                    found_car = relaxed["cars"][0]
                    cond_label = (
                        "مستعملة"
                        if found_car.condition == "used"
                        else "جديدة"
                        if found_car.condition == "new"
                        else str(found_car.condition)
                    )
                    update["catalog_result"] = {
                        "type": "fallback_condition",
                        "car_name": f"{found_car.brand} {found_car.model}".strip(),
                        "available_condition_text": cond_label,
                    }
                    return update
                update["catalog_result"] = self._diagnose_no_results(preferences)
                return update

            context = self.context.load(session_id)
            update.update(self._context_update(context))
            active = context.active_snapshot or {"items": []}
            update["catalog_result"] = {
                "type": "recommendations",
                "cars": active["items"],
                "snapshot_id": active.get("id"),
                **(
                    {
                        "soft_condition_preferred": soft_conditions[0],
                        "soft_condition_used": chosen_soft_condition,
                    }
                    if soft_conditions and chosen_soft_condition
                    else {}
                ),
            }
            return update
        except (
            ConversationContextError,
            VisibleRecommendationError,
            LookupError,
            ValueError,
            SQLAlchemyError,
        ):
            self.session.rollback()
            update["errors"] = self._errors(state, "catalog_unavailable")
            return update

    def _compose_response(self, state: AgentState) -> AgentState:
        update = self._trace(state, "compose_response")
        guard_error = state.get("guard_error")
        errors = state.get("errors", [])
        if guard_error:
            update["response"] = render_error(guard_error)
            return update
        if errors:
            update["response"] = render_error(errors[0])
            return update

        semantics = dict(state.get("turn_semantics") or {})
        if semantics.get("budget_change_unspecified"):
            current_budget = (state.get("preferences") or {}).get("max_price")
            if current_budget is not None:
                update["response"] = (
                    f"أكيد، ممكن نزود الميزانية عن {float(current_budget):,.0f} جنيه. "
                    "تحب تخلي الحد الجديد كام تقريبًا؟"
                )
            else:
                update["response"] = "أكيد، ممكن نزود الميزانية. تحب تخلي الحد كام تقريبًا؟"
            return update

        fallback = self._deterministic_fallback(state)
        if isinstance(self.llm, DeterministicAgentLLM):
            update["response"] = fallback
            return update

        # If RAG has no verified support, do not invite a language model to improvise policy.
        if state.get("route") == "rag" and not state.get("knowledge_supported", False):
            update["response"] = fallback
            return update

        verified_context = self._verified_response_context(state, fallback)
        try:
            response = self.llm.compose_general(
                state.get("normalized_message", ""),
                verified_context=verified_context,
            ).strip()
        except AgentLLMError:
            update["response"] = fallback
            update["errors"] = self._errors(state, "composition_failed")
            return update

        if not self._composition_is_grounded(response, state, verified_context):
            update["response"] = fallback
            update["errors"] = self._errors(state, "composition_rejected")
            return update

        update["response"] = response
        return update

    def _deterministic_fallback(self, state: AgentState) -> str:
        route = state.get("route")
        if route == "catalog":
            return render_catalog(state.get("catalog_result"))
        if route == "rag":
            return render_knowledge(
                state.get("knowledge_supported", False),
                state.get("grounded_knowledge"),
            )
        if route == "business_gate":
            return render_business_action(
                state.get("action_status"),
                user_message=state.get("normalized_message"),
            )
        return DeterministicAgentLLM().compose_general(
            state.get("normalized_message", ""),
            verified_context={},
        )

    def _verified_response_context(
        self,
        state: AgentState,
        fallback: str,
    ) -> dict[str, Any]:
        memory_context: dict[str, Any] = {}
        session_id = state.get("session_id")
        if session_id:
            try:
                memory_context = self.customer_memory.load(uuid.UUID(session_id)).safe_context()
            except (LookupError, TypeError, ValueError):
                memory_context = {}

        pending = state.get("pending_action") or {}
        pending_fields = dict(pending.get("fields") or {})
        action = dict(state.get("action_status") or {})
        safe_action_keys = {
            "status",
            "intent",
            "request_id",
            "lead_id",
            "car_id",
            "preferred_date",
            "preferred_time",
            "missing_fields",
            "candidate_request_ids",
            "memory_fields_used",
            "customer_memory_scope",
        }

        return {
            "authoritative_fallback": fallback,
            "route": state.get("route"),
            "intent": state.get("intent"),
            "turn_semantics": state.get("turn_semantics", {}),
            "recent_messages": state.get("recent_messages", [])[-8:],
            "vehicle_preferences": state.get("preferences", {}),
            "selected_car_id": state.get("selected_car_id"),
            "pending_action": {
                "type": pending.get("type"),
                "collected_fields": sorted(pending_fields),
            },
            "customer_memory": memory_context,
            "catalog_result": state.get("catalog_result"),
            "grounded_knowledge": state.get("grounded_knowledge"),
            "action_result": {key: action.get(key) for key in safe_action_keys if key in action},
        }

    def _composition_is_grounded(
        self,
        response: str,
        state: AgentState,
        verified_context: dict[str, Any],
    ) -> bool:
        if not response or len(response) > 2400:
            return False

        source = " ".join(
            (
                state.get("normalized_message", ""),
                json.dumps(verified_context, ensure_ascii=False, default=str),
            )
        )
        allowed_numbers = self._numbers(source)
        if any(number not in allowed_numbers for number in self._numbers(response)):
            return False

        if state.get("route") != "business_gate":
            return True

        action = state.get("action_status") or {}
        status = action.get("status")
        if status != "success":
            success_claims = ("تم تسجيل", "اتسجل بنجاح", "تم إلغاء", "اتلغى بنجاح")
            return not any(claim in response for claim in success_claims)

        intent = action.get("intent")
        required_id = action.get("lead_id") if intent == "sales_lead" else action.get("request_id")
        if not isinstance(required_id, int):
            return False
        if required_id not in self._numbers(response):
            return False

        if intent == "test_drive":
            unsafe_confirmation = (
                "تم تأكيد الموعد",
                "الموعد مؤكد",
                "الحجز مؤكد",
                "اتأكد الموعد نهائيا",
                "اتأكد الموعد نهائيًا",
            )
            if any(claim in response for claim in unsafe_confirmation):
                return False
        return True

    def _resolve_visible_reference(
        self,
        state: AgentState,
        message: str,
        *,
        intent: str,
    ) -> int | None:
        if intent not in {"car_selection", "car_details", "test_drive"}:
            return None
        snapshot = state.get("active_snapshot") or {}
        items = list(snapshot.get("items") or [])
        if not items:
            return None

        brand = explicit_brand_from_message(message)
        model = explicit_model_from_message(message)
        matches = []
        if brand or model:
            for item in items:
                car = item.get("car") or {}
                if brand and str(car.get("brand") or "").casefold() != brand.casefold():
                    continue
                if model and str(car.get("model") or "").casefold() != model.casefold():
                    continue
                matches.append(item)
            if len(matches) == 1:
                return int(matches[0]["position"])

        selected_car_id = state.get("selected_car_id")
        text = message.casefold()
        if selected_car_id is not None and any(marker in text for marker in _DEICTIC_CAR_MARKERS):
            match = next(
                (item for item in items if int(item.get("car_id")) == int(selected_car_id)),
                None,
            )
            if match is not None:
                return int(match["position"])
        return None

    def _resolve_catalog_model(self, brand: str | None, requested: str | None) -> str | None:
        if not requested:
            return None
        filters = {"brand": brand} if brand else {}
        cars = self.catalog.search(filters, sort_by="year_desc", limit=100)
        models = list(dict.fromkeys(str(car.model) for car in cars if car.model))
        requested_norm = self._entity_norm(requested)
        for candidate in models:
            if self._entity_norm(candidate) == requested_norm:
                return candidate
        partial = [
            candidate
            for candidate in models
            if requested_norm
            and (
                requested_norm in self._entity_norm(candidate)
                or self._entity_norm(candidate) in requested_norm
            )
        ]
        return partial[0] if len(partial) == 1 else None

    def _diagnose_no_results(self, preferences: dict[str, Any]) -> dict[str, Any]:
        brand = str(preferences.get("brand") or "").strip() or None
        model = str(preferences.get("model") or "").strip() or None
        identity = {
            key: value
            for key, value in (("brand", brand), ("model", model))
            if value
        }
        identity_cars = (
            self.catalog.search(identity, sort_by="price_asc", limit=20)
            if identity
            else []
        )

        if identity_cars:
            label = " ".join(value for value in (brand, model) if value)
            max_price = preferences.get("max_price")
            cheapest = min(float(car.price_egp) for car in identity_cars)
            if max_price is not None and cheapest > float(max_price):
                return {
                    "type": "clarification",
                    "message": (
                        f"{label} موجودة حسب الكتالوج المسجل، لكن أقل سعر مسجل لقيته "
                        f"{cheapest:,.0f} جنيه، وده أعلى من ميزانيتك الحالية "
                        f"{float(max_price):,.0f} جنيه. لو حابب تزود الميزانية قولي الحد الجديد."
                    ),
                }

            requested_condition = str(preferences.get("condition") or "").strip()
            conditions = {str(car.condition) for car in identity_cars if car.condition}
            if requested_condition and requested_condition not in conditions:
                available = "، ".join(sorted(conditions)) or "بحالة مختلفة"
                return {
                    "type": "clarification",
                    "message": (
                        f"{label} موجودة في الكتالوج، لكن مش بالحالة المطلوبة حاليًا. "
                        f"الحالات المسجلة: {available}."
                    ),
                }

            return {
                "type": "clarification",
                "message": (
                    f"{label} موجودة في الكتالوج المسجل، لكن مش مطابقة لكل الشروط الحالية. "
                    "لو تحب نقدر نخفف شرط من السعر أو الحالة أو نوع العربية."
                ),
            }

        if model:
            label = " ".join(value for value in (brand, model) if value)
            return {
                "type": "clarification",
                "message": (
                    f"ملقتش {label} مطابقة كاسم موديل في الكتالوج المسجل. "
                    "لو تحب اكتبلي اسم الموديل بطريقة تانية أو أعرّضلك موديلات نفس الماركة."
                ),
            }
        return {"type": "no_results"}

    @staticmethod
    def _catalog_model_token(message: str) -> str | None:
        text = message.translate(_ARABIC_DIGITS).casefold()
        if any(marker in text for marker in ("الف", "ألف", "ميزانية", "ميزانيه", "معايا", "سعر")):
            return None
        match = re.search(r"(?<!\d)(\d{3}[a-z]?)(?!\d)", text)
        return match.group(1) if match else None

    @staticmethod
    def _entity_norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    @staticmethod
    def _numbers(text: str) -> set[int]:
        normalized = str(text).translate(_ARABIC_DIGITS)
        return {int(value) for value in re.findall(r"\d+", normalized)}
