"""Actual LangGraph topology and routing rules."""

from langgraph.graph import END, START, StateGraph

from app.agent.state import AgentState


def _route_intent(state: AgentState) -> str:
    return state["intent"]


def _route_after_vehicle(state: AgentState) -> str:
    return "knowledge" if state["analysis"]["needs_knowledge"] else "respond"


def build_agent_graph(nodes):
    graph = StateGraph(AgentState)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("analyze_request", nodes.analyze_request)
    graph.add_node("vehicle_search", nodes.search_vehicles)
    graph.add_node("knowledge_search", nodes.search_knowledge)
    graph.add_node("generate_response", nodes.generate_response)
    graph.add_node("persist_response", nodes.persist_response)
    graph.add_edge(START, "load_context")
    graph.add_edge("load_context", "analyze_request")
    graph.add_conditional_edges(
        "analyze_request",
        _route_intent,
        {
            "vehicle_search": "vehicle_search",
            "knowledge": "knowledge_search",
            "mixed": "vehicle_search",
            "general": "generate_response",
            "unsupported": "generate_response",
        },
    )
    graph.add_conditional_edges(
        "vehicle_search", _route_after_vehicle,
        {"knowledge": "knowledge_search", "respond": "generate_response"},
    )
    graph.add_edge("knowledge_search", "generate_response")
    graph.add_edge("generate_response", "persist_response")
    graph.add_edge("persist_response", END)
    return graph.compile()
