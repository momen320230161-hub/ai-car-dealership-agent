"""Node implementations for the dealership StateGraph."""

from uuid import UUID

from app.agent.schemas import RequestAnalysis, VehicleFilters


class AgentNodes:
    def __init__(self, *, llm, vehicles, retrieval, conversations, rag_top_k=5, min_similarity=None):
        self.llm = llm
        self.vehicles = vehicles
        self.retrieval = retrieval
        self.conversations = conversations
        self.rag_top_k = rag_top_k
        self.min_similarity = min_similarity

    def load_context(self, state):
        history = self.conversations.recent_history(
            UUID(state["conversation_id"]), exclude_message_id=UUID(state["customer_message_id"])
        )
        return {"history": history}

    def analyze_request(self, state):
        analysis = self.llm.analyze_request(state["user_message"], state.get("history", []))
        return {
            "analysis": analysis.model_dump(),
            "intent": analysis.intent,
            "language": analysis.language,
        }

    def search_vehicles(self, state):
        filters = VehicleFilters.model_validate(state["analysis"]["vehicle_filters"])
        results = self.vehicles.search(filters)
        return {"vehicle_results": [item.model_dump(mode="json") for item in results]}

    def search_knowledge(self, state):
        query = state["analysis"].get("knowledge_query") or state["user_message"]
        results = self.retrieval.search_knowledge(
            query, top_k=self.rag_top_k, min_similarity=self.min_similarity
        )
        safe_results = [
            {
                "document_title": item.document_title,
                "category": item.category,
                "content": item.content,
                "similarity": round(item.similarity, 6),
                "source_type": item.source_type,
                "source_reference": item.source_reference,
            }
            for item in results
        ]
        return {"knowledge_results": safe_results}

    def generate_response(self, state):
        sources = []
        if state.get("vehicle_results"):
            sources.append("vehicle inventory")
        sources.extend(
            f"knowledge: {item['document_title']}" for item in state.get("knowledge_results", [])
        )
        return {"final_response": self.llm.generate_response(state), "sources": sources}

    def persist_response(self, state):
        self.conversations.add_message(
            UUID(state["conversation_id"]), "agent", state["final_response"]
        )
        return {"response_persisted": True}
