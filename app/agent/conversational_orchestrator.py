"""Production conversational layer over the deterministic LangGraph sales orchestrator."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from app.agent.business_rendering import render_business_action
from app.agent.catalog_qualification import qualify_catalog_search
from app.domain.catalog_language import explicit_brand_from_message, explicit_model_from_message
from app.agent.graph import SalesOrchestrator
from app.agent.llm import AgentLLMError, DeterministicAgentLLM
from app.agent.rendering import render_catalog, render_error, render_knowledge
from app.agent.schemas import explicit_visible_references
from app.agent.state import AgentState
from app.agent.turn_semantics import analyze_turn
from app.services.business_action_parsing import parse_business_fields
from app.services.catalog_preference_state_service import CatalogPreferenceStateService
from app.services.conversation_context_service import (
    ConversationContext,
    ConversationContextError,
)
from app.services.conversation_dialogue_state_service import (
    ConversationDialogueStateError,
    ConversationDialogueStateService,
)
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
_RECOMMEND_GOAL_MARKERS = (
    "رشح",
    "اقترح",
    "وريني",
    "ورّيني",
    "اعرض",
    "هات اللي عندك",
    "هات ال عندك",
    "نفسي اركب",
    "نفسي أركب",
    "عايز عربية",
    "عاوز عربية",
    "recommend",
    "suggest",
    "show me",
)
_REQUIRED_BY_ACTION = {
    "test_drive": {"car_id", "customer_name", "phone", "preferred_date", "preferred_time"},
    "sales_lead": {"customer_name", "phone"},
    "cancel_test_drive": {"request_id"},
}
_PENDING_FIELD_LABELS = {
    "car_id": "العربية",
    "customer_name": "الاسم",
    "phone": "رقم الموبايل",
    "preferred_date": "اليوم أو التاريخ",
    "preferred_time": "الوقت",
    "request_id": "رقم الطلب",
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
_REFERENCE_LANGUAGE_MARKERS = (
    "قصدي",
    "اقصد",
    "أقصد",
    "جميلة",
    "جميله",
    "حلوة",
    "حلوه",
    "جامدة",
    "جامده",
    "عجبتني",
    "عاجباني",
    "عاجبني",
    "اختار",
    "تفاصيل",
    "مواصفات",
    "حصان",
    "الأولى",
    "الاولى",
    "اول عربية",
    "أول عربية",
    "التانية",
    "الثانية",
    "تاني عربية",
    "التالتة",
    "الثالثة",
    "تالت عربية",
    "this one",
    "first car",
    "second car",
    "third car",
)
_DETAIL_REFERENCE_MARKERS = (
    "تفاصيل",
    "مواصفات",
    "حصان",
    "قوة",
    "سعرها",
    "عدادها",
    "ممشاها",
    "عنها",
    "details",
    "specs",
    "horsepower",
)
_CONFUSION_MARKERS = (
    "مش فاهم",
    "مش فاهمة",
    "مش فاهمم",
    "يعني ايه",
    "يعني إيه",
    "مش واضح",
    "وضحلي",
    "وضح لي",
    "what do you mean",
)


class ConversationalSalesOrchestrator(SalesOrchestrator):
    """Keep deterministic execution, but make routing/memory/language conversational."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        provided_state_service = kwargs.get("state_service")
        provided_business_service = kwargs.get("business_action_service")
        super().__init__(*args, **kwargs)

        self.customer_memory = CustomerMemoryService(self.session)
        self.dialogue_state_service = ConversationDialogueStateService(self.session)
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

        legacy_semantics = analyze_turn(message, state.get("preferences", {}), extracted)

        llm_action = str(update.get("llm_dialogue_action") or "")
        llm_clears = {
            str(field)
            for field in (update.get("llm_preference_clears") or [])
            if str(field)
        }
        llm_budget_change = str(update.get("llm_budget_change") or "none")
        llm_condition_order = list(
            dict.fromkeys(
                str(value)
                for value in (update.get("llm_condition_preference_order") or [])
                if str(value) in {"new", "used"}
            )
        )
        if len(llm_condition_order) != 2:
            llm_condition_order = []

        catalog_semantic_action = llm_action in {
            "recommend",
            "refine",
            "broaden",
            "reset",
            "paginate",
        }
        effective_llm_clears = (
            set(llm_clears)
            if catalog_semantic_action or update.get("intent") == "catalog_search"
            else set()
        )
        effective_condition_order = (
            llm_condition_order
            if catalog_semantic_action or update.get("intent") == "catalog_search"
            else []
        )
        if effective_condition_order:
            effective_llm_clears.add("condition")

        has_llm_semantics = bool(
            llm_action
            or llm_clears
            or llm_budget_change != "none"
            or effective_condition_order
        )

        if has_llm_semantics:
            # Once the LLM returns semantic control data, build the control plane from
            # that schema only. Legacy phrase analysis remains a compatibility fallback,
            # never a hidden second decision-maker.
            semantics_data = {
                "source": "llm",
                "mode": llm_action or "refine",
                "clear_fields": sorted(effective_llm_clears),
                "force_clear_fields": sorted(effective_llm_clears),
                "soft_condition_order": effective_condition_order,
                "force_catalog_search": False,
                "pagination_requested": False,
                "more_results_question": False,
                "budget_change_unspecified": False,
                "budget_change": llm_budget_change,
            }

            control_only_turn = llm_action in {
                "social",
                "continue",
                "discuss_budget",
            }
            if control_only_turn:
                extracted = {}

            for field in effective_llm_clears:
                extracted[field] = None

            if llm_action == "reset":
                for field in state.get("preferences", {}):
                    extracted[field] = None
            if llm_action == "paginate":
                semantics_data["pagination_requested"] = True
                semantics_data["force_catalog_search"] = True
            elif llm_action == "broaden":
                semantics_data["force_catalog_search"] = True
            elif llm_action == "recommend":
                semantics_data["force_catalog_search"] = bool(
                    state.get("preferences") or extracted or effective_llm_clears
                )
            elif llm_action == "refine" and (state.get("preferences") or extracted):
                semantics_data["force_catalog_search"] = True

            if llm_budget_change == "remove_limit":
                extracted["min_price"] = None
                extracted["max_price"] = None
            elif llm_budget_change in {"increase_unspecified", "decrease_unspecified"}:
                extracted.pop("min_price", None)
                extracted.pop("max_price", None)
                semantics_data["budget_change_unspecified"] = True
                update["intent"] = "general"

            if (
                semantics_data.get("force_catalog_search")
                and update.get("intent") == "general"
                and not semantics_data.get("budget_change_unspecified")
            ):
                update["intent"] = "catalog_search"
        else:
            # Offline fixtures and older adapters retain the deterministic fallback.
            semantics_data = legacy_semantics.as_dict()
            if legacy_semantics.budget_change_unspecified:
                update["intent"] = "general"
                extracted = {}
                semantics_data["budget_change"] = "increase_unspecified"
            else:
                forced = set(legacy_semantics.force_clear_fields)
                for field in legacy_semantics.clear_fields:
                    if field in forced or field not in extracted:
                        extracted[field] = None
                if (
                    legacy_semantics.force_catalog_search
                    and update.get("intent") == "general"
                ):
                    update["intent"] = "catalog_search"

        # Resolve references while the previous visible snapshot is still authoritative.
        # First trust an LLM ordinal only if that exact visible position exists; otherwise
        # resolve deterministic ordinals or unique visible brand/model references. This keeps
        # reference turns from mutating filters and invalidating the list before resolution.
        explicit_positions = explicit_visible_references(message)
        resolved_reference = None
        if explicit_positions:
            resolved_reference = self._validated_llm_visible_reference(
                state,
                explicit_positions[0],
            )
        selector_intent = str(update.get("intent") or "general")
        if resolved_reference is None and selector_intent in {
            "general",
            "car_selection",
            "car_details",
            "test_drive",
            "sales_lead",
        }:
            resolved_reference = self._resolve_visible_selector(
                state,
                update.get("visible_reference_selector"),
            )
        if resolved_reference is None:
            resolved_reference = self._validated_llm_visible_reference(
                state,
                update.get("car_reference"),
            )
        if resolved_reference is None:
            resolved_reference = self._resolve_visible_reference(
                state,
                message,
                intent=str(update.get("intent") or "general"),
                extracted_preferences=extracted,
            )
        if resolved_reference is not None:
            current_intent = str(update.get("intent") or "general")
            if current_intent in {"general", "catalog_search"}:
                update["intent"] = (
                    "car_details" if self._looks_like_detail_reference(message) else "car_selection"
                )
            update["car_reference"] = resolved_reference
            semantics_data["resolved_visible_reference"] = resolved_reference
            semantics_data["mode"] = "reference"
            if update.get("intent") in {
                "car_selection",
                "car_details",
                "test_drive",
                "sales_lead",
            }:
                extracted.pop("brand", None)
                extracted.pop("model", None)

        current_goal = str((state.get("dialogue_state") or {}).get("catalog_goal") or "")
        resolved_intent = str(update.get("intent") or "general")
        if resolved_intent in _BUSINESS_INTENTS or resolved_intent == "car_selection":
            semantics_data["catalog_goal_operation"] = "clear"
        elif (
            llm_action == "recommend"
            or (
                not has_llm_semantics
                and self._explicit_recommendation_goal(message)
            )
        ) and resolved_intent in {"catalog_search", "general"}:
            semantics_data["catalog_goal_operation"] = "recommend"
            if resolved_intent == "general" and (state.get("preferences") or extracted):
                update["intent"] = "catalog_search"
                semantics_data["force_catalog_search"] = True
        elif (
            current_goal == "recommend"
            and extracted
            and resolved_intent in {"catalog_search", "general"}
            and not semantics_data.get("budget_change_unspecified")
        ):
            update["intent"] = "catalog_search"
            semantics_data["force_catalog_search"] = True
            semantics_data["resume_catalog_goal"] = True

        update["extracted_preferences"] = extracted
        update["turn_semantics"] = semantics_data
        return update

    def _update_state(self, state: AgentState) -> AgentState:
        """Persist filter changes and non-filter conversational goal changes separately."""
        update = super()._update_state(state)
        if "state_update_failed" in update.get("errors", []):
            return update

        operation = str((state.get("turn_semantics") or {}).get("catalog_goal_operation") or "")
        if operation not in {"recommend", "clear"}:
            return update
        try:
            session_id = uuid.UUID(state["session_id"])
            goal = "recommend" if operation == "recommend" else None
            self.dialogue_state_service.set_catalog_goal(session_id, goal)
            update.update(self._context_update(self.context.load(session_id)))
        except (
            ConversationContextError,
            ConversationDialogueStateError,
            TypeError,
            ValueError,
            SQLAlchemyError,
        ):
            update["errors"] = self._errors(state, "state_update_failed")
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
        field_hint = str(state.get("pending_field_answer") or "none")
        parsed = parse_business_fields(
            message,
            allow_bare_name=allow_bare_name,
            allow_single_name=(
                allow_bare_name
                and field_hint == "customer_name"
            ),
        )
        explicit = set(parsed.as_json_fields())
        if explicit & required:
            return True
        if self._looks_like_pending_time_answer(pending, missing, message):
            return True
        if intent == "general" and state.get("llm_dialogue_action") == "continue":
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

            active = state.get("active_snapshot") or {}
            items = list(active.get("items") or [])
            if items:
                update = self._trace(state, "catalog_node")
                positions = " ولا ".join(str(item["position"]) for item in items)
                update["catalog_result"] = {
                    "type": "clarification",
                    "message": f"تقصد رقم كام من القائمة؟ {positions}؟",
                }
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

        pending_help = self._pending_confusion_response(state)
        if pending_help is not None:
            update["response"] = pending_help
            return update

        semantics = dict(state.get("turn_semantics") or {})
        if semantics.get("budget_change_unspecified"):
            current_budget = (state.get("preferences") or {}).get("max_price")
            direction = str(semantics.get("budget_change") or "increase_unspecified")
            if direction == "decrease_unspecified":
                if current_budget is not None:
                    update["response"] = (
                        f"تمام، نقدر نقلل الميزانية عن {float(current_budget):,.0f} جنيه. "
                        "تحب تخلي الحد الجديد كام تقريبًا؟"
                    )
                else:
                    update["response"] = "تمام، تحب نخلي الحد الأقصى للميزانية كام تقريبًا؟"
            elif current_budget is not None:
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
        }

        return {
            "authoritative_fallback": fallback,
            "route": state.get("route"),
            "intent": state.get("intent"),
            "turn_semantics": state.get("turn_semantics", {}),
            "recent_messages": state.get("recent_messages", [])[-8:],
            "vehicle_preferences": state.get("preferences", {}),
            "dialogue_state": state.get("dialogue_state", {}),
            "selected_car_id": state.get("selected_car_id"),
            "pending_action": {
                "type": pending.get("type"),
                "collected_fields": sorted(pending_fields),
            },
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

    def _resolve_visible_selector(
        self,
        state: AgentState,
        selector: Any,
    ) -> int | None:
        """Resolve semantic visible-car descriptions against verified snapshot facts only."""
        if not isinstance(selector, dict):
            return None
        field = str(selector.get("field") or "none")
        operator = str(selector.get("operator") or "none")
        value = str(selector.get("value") or "").strip()
        if field == "none" or operator == "none":
            return None

        snapshot = state.get("active_snapshot") or {}
        items = list(snapshot.get("items") or [])
        if not items:
            return None

        numeric_fields = {"price_egp", "mileage_km", "year"}
        categorical_fields = {
            "condition",
            "transmission",
            "body_type",
            "fuel_type",
        }
        if field in numeric_fields and operator in {"min", "max"}:
            candidates: list[tuple[int, float]] = []
            for item in items:
                car = item.get("car") or {}
                raw = car.get(field)
                try:
                    numeric = float(raw)
                except (TypeError, ValueError):
                    continue
                candidates.append((int(item["position"]), numeric))
            if not candidates:
                return None
            target = (
                min(number for _, number in candidates)
                if operator == "min"
                else max(number for _, number in candidates)
            )
            matches = [position for position, number in candidates if number == target]
            return matches[0] if len(matches) == 1 else None

        if field in categorical_fields and operator == "equals" and value:
            wanted = self._entity_norm(value)
            matches: list[int] = []
            for item in items:
                car = item.get("car") or {}
                actual = str(car.get(field) or "")
                if self._entity_norm(actual) == wanted:
                    matches.append(int(item["position"]))
            return matches[0] if len(matches) == 1 else None
        return None

    def _validated_llm_visible_reference(
        self,
        state: AgentState,
        reference: Any,
    ) -> int | None:
        if reference is None:
            return None
        try:
            position = int(reference)
        except (TypeError, ValueError):
            return None
        snapshot = state.get("active_snapshot") or {}
        items = list(snapshot.get("items") or [])
        exists = any(int(item.get("position", -1)) == position for item in items)
        return position if exists else None

    def _resolve_visible_reference(
        self,
        state: AgentState,
        message: str,
        *,
        intent: str,
        extracted_preferences: dict[str, Any] | None = None,
    ) -> int | None:
        snapshot = state.get("active_snapshot") or {}
        items = list(snapshot.get("items") or [])
        if not items:
            return None

        ordinal = self._explicit_visible_ordinal(message)
        if ordinal is not None:
            exists = any(int(item.get("position", -1)) == ordinal for item in items)
            if exists:
                return ordinal

        reference_intents = {"car_selection", "car_details", "test_drive", "sales_lead"}
        if intent not in reference_intents and not self._looks_like_reference_turn(message):
            return None

        extracted = extracted_preferences or {}
        brand = explicit_brand_from_message(message) or self._text_value(extracted.get("brand"))
        model = explicit_model_from_message(message) or self._text_value(extracted.get("model"))
        matches: list[dict[str, Any]] = []
        if brand or model:
            for item in items:
                car = item.get("car") or {}
                if brand and not self._entity_matches(str(car.get("brand") or ""), brand):
                    continue
                if model and not self._entity_matches(str(car.get("model") or ""), model):
                    continue
                matches.append(item)
            if len(matches) == 1:
                return int(matches[0]["position"])

        direct_matches: list[dict[str, Any]] = []
        for item in items:
            car = item.get("car") or {}
            values = (str(car.get("model") or ""), str(car.get("brand") or ""))
            mentions_visible_value = any(
                self._message_mentions_catalog_value(message, value)
                for value in values
                if value
            )
            if mentions_visible_value:
                direct_matches.append(item)
        if len(direct_matches) == 1:
            return int(direct_matches[0]["position"])

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

    def _pending_confusion_response(self, state: AgentState) -> str | None:
        message = state.get("normalized_message", "").casefold()
        if not any(marker in message for marker in _CONFUSION_MARKERS):
            return None
        pending = state.get("pending_action") or {}
        pending_type = str(pending.get("type") or "")
        required = _REQUIRED_BY_ACTION.get(pending_type, set())
        if not required:
            return None
        fields = dict(pending.get("fields") or {})
        missing = [name for name in required if fields.get(name) in (None, "")]
        if not missing:
            return None
        if pending_type == "test_drive" and missing == ["preferred_time"]:
            return (
                "قصدي تحدد الساعة ومعاها صباح ولا عصر/مساء، مثلاً 4 العصر، "
                "عشان ما نسجلش وقت غلط."
            )
        labels = [_PENDING_FIELD_LABELS.get(name, name) for name in sorted(missing)]
        joined = "، ".join(labels)
        action_name = "طلب التست درايف" if pending_type == "test_drive" else "الطلب"
        return f"إحنا بنكمل {action_name}. الناقص بس: {joined}."

    @staticmethod
    def _looks_like_pending_time_answer(
        pending: dict[str, Any],
        missing: set[str],
        message: str,
    ) -> bool:
        if "preferred_time" not in missing:
            return False
        text = str(message or "").translate(_ARABIC_DIGITS).casefold().strip()
        if re.fullmatch(r"(?:(?:الساعة|الساعه|ساعة|ساعه)\s*)?(?:[1-9]|1[0-2])", text):
            return True
        if pending.get("ambiguous_time_hour") is None:
            return False
        return bool(
            re.fullmatch(
                r"(?:الصباح|الصبح|صباح(?:ا|اً)?|المساء|مساء(?:ا|ً)?|"
                r"العصر|عصر(?:ا|اً)?|الظهر|ظهر(?:ا|اً)?|am|pm)",
                text,
                flags=re.IGNORECASE,
            )
        )

    @staticmethod
    def _explicit_visible_ordinal(message: str) -> int | None:
        text = str(message or "").casefold()
        ordinal_terms = {
            1: ("الأولى", "الاولى", "الأول", "الاول", "اول عربية", "أول عربية", "first"),
            2: ("التانية", "التانيه", "الثاني", "الثانية", "الثانيه", "second"),
            3: ("التالتة", "التالته", "الثالث", "الثالثة", "الثالثه", "third"),
        }
        for position, terms in ordinal_terms.items():
            if any(term in text for term in terms):
                return position
        return None

    @staticmethod
    def _looks_like_reference_turn(message: str) -> bool:
        text = str(message or "").casefold()
        return any(marker in text for marker in _REFERENCE_LANGUAGE_MARKERS)

    @staticmethod
    def _looks_like_detail_reference(message: str) -> bool:
        text = str(message or "").casefold()
        return any(marker in text for marker in _DETAIL_REFERENCE_MARKERS)

    @staticmethod
    def _message_mentions_catalog_value(message: str, candidate: str) -> bool:
        value = str(candidate or "").strip().casefold()
        if not value:
            return False
        text = str(message or "").casefold()
        return bool(re.search(rf"(?<!\w){re.escape(value)}(?!\w)", text))

    @staticmethod
    def _explicit_recommendation_goal(message: str) -> bool:
        text = str(message or "").casefold()
        return any(marker in text for marker in _RECOMMEND_GOAL_MARKERS)

    @staticmethod
    def _catalog_model_token(message: str) -> str | None:
        text = message.translate(_ARABIC_DIGITS).casefold()
        if any(marker in text for marker in ("الف", "ألف", "ميزانية", "ميزانيه", "معايا", "سعر")):
            return None
        match = re.search(r"(?<!\d)(\d{3}[a-z]?)(?!\d)", text)
        return match.group(1) if match else None

    @classmethod
    def _entity_matches(cls, candidate: str, requested: str) -> bool:
        candidate_norm = cls._entity_norm(candidate)
        requested_norm = cls._entity_norm(requested)
        if not candidate_norm or not requested_norm:
            return False
        return (
            candidate_norm == requested_norm
            or candidate_norm.startswith(requested_norm)
            or requested_norm.startswith(candidate_norm)
        )

    @staticmethod
    def _text_value(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _entity_norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value).casefold())

    @staticmethod
    def _numbers(text: str) -> set[int]:
        normalized = str(text).translate(_ARABIC_DIGITS)
        return {int(value) for value in re.findall(r"\d+", normalized)}

    @staticmethod
    def _context_update(context: ConversationContext) -> AgentState:
        update = SalesOrchestrator._context_update(context)
        update["dialogue_state"] = context.dialogue_state
        return update
