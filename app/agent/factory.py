"""Runtime factory for the customer-facing Sales Orchestrator."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session

from app.agent.conversational_orchestrator import ConversationalSalesOrchestrator
from app.agent.graph import SalesOrchestrator
from app.agent.llm import build_agent_llm
from app.rag.embeddings import build_embedding_provider


def build_sales_orchestrator(session: Session, config: Mapping[str, Any]) -> SalesOrchestrator:
    """Build the production graph from application configuration.

    The production runtime uses the conversational hardening layer while retaining the
    original SalesOrchestrator interface and deterministic services underneath it.
    """
    return ConversationalSalesOrchestrator(
        session,
        build_agent_llm(config),
        build_embedding_provider(config),
        max_message_length=int(config.get("AGENT_MAX_MESSAGE_LENGTH", 4000)),
        recent_message_limit=int(config.get("AGENT_RECENT_MESSAGE_LIMIT", 12)),
        recommendation_limit=int(config.get("AGENT_RECOMMENDATION_LIMIT", 3)),
        rag_top_k=int(config.get("RAG_TOP_K", 4)),
        rag_max_top_k=int(config.get("RAG_MAX_TOP_K", 20)),
        rag_min_score=config.get("RAG_MIN_SCORE"),
    )
