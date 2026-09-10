"""Public, framework-neutral entry point for one agent turn."""

from time import perf_counter

from flask import current_app

from app.agent.graph import build_agent_graph
from app.agent.nodes import AgentNodes
from app.agent.schemas import AgentResult
from app.services.conversation_service import ConversationService
from app.services.gemini_llm import GeminiLLMService
from app.services.retrieval import RetrievalService
from app.services.vehicle_search import VehicleSearchService


class DealershipAgent:
    def __init__(self, *, llm=None, vehicles=None, retrieval=None, conversations=None):
        config = current_app.config
        conversations = conversations or ConversationService(
            history_limit=config["AGENT_HISTORY_MAX_MESSAGES"]
        )
        nodes = AgentNodes(
            llm=llm or GeminiLLMService(),
            vehicles=vehicles or VehicleSearchService(),
            retrieval=retrieval or RetrievalService(),
            conversations=conversations,
            rag_top_k=config["AGENT_RAG_TOP_K"],
            min_similarity=config["AGENT_RAG_MIN_SIMILARITY"],
        )
        self.conversations = conversations
        self.graph = build_agent_graph(nodes)

    def ask(self, message: str, *, conversation_id=None) -> AgentResult:
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be non-empty")
        conversation = self.conversations.get_or_create(conversation_id)
        customer_message = self.conversations.add_message(conversation.id, "customer", message.strip())
        started = perf_counter()
        try:
            result = self.graph.invoke({
                "conversation_id": str(conversation.id),
                "customer_message_id": str(customer_message.id),
                "user_message": message.strip(),
                "vehicle_results": [],
                "knowledge_results": [],
                "sources": [],
            })
        except Exception as error:
            current_app.logger.warning(
                "Agent turn failed conversation_id=%s error_type=%s elapsed_ms=%d",
                conversation.id, type(error).__name__, (perf_counter() - started) * 1000,
            )
            raise
        if not result.get("response_persisted"):
            raise RuntimeError("agent response was not persisted")
        current_app.logger.info(
            "Agent turn complete conversation_id=%s intent=%s vehicle_results=%d "
            "knowledge_results=%d elapsed_ms=%d",
            conversation.id, result["intent"], len(result.get("vehicle_results", [])),
            len(result.get("knowledge_results", [])), (perf_counter() - started) * 1000,
        )
        return AgentResult.model_validate({
            "conversation_id": conversation.id,
            "intent": result["intent"],
            "language": result["language"],
            "response": result["final_response"],
            "vehicle_results": result.get("vehicle_results", []),
            "knowledge_sources": result.get("knowledge_results", []),
            "sources": result.get("sources", []),
        })
