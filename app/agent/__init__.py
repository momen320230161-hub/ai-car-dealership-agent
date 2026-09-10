"""LangGraph-powered dealership assistant."""

__all__ = ["DealershipAgent"]


def __getattr__(name):
    if name == "DealershipAgent":
        from app.agent.service import DealershipAgent

        return DealershipAgent
    raise AttributeError(name)
