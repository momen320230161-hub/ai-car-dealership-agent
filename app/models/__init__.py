"""ORM Domain Models package."""

from app.models.base import GUID, Base, PortableJSON, TimestampMixin, utc_now
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.knowledge import KnowledgeChunk, KnowledgeDocument
from app.models.lead import SalesLead
from app.models.message import ChatMessage
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem
from app.models.test_drive import TestDriveRequest

__all__ = [
    "Base",
    "TimestampMixin",
    "utc_now",
    "GUID",
    "PortableJSON",
    "Car",
    "ConversationSession",
    "ChatMessage",
    "RecommendationSnapshot",
    "RecommendationSnapshotItem",
    "TestDriveRequest",
    "SalesLead",
    "KnowledgeDocument",
    "KnowledgeChunk",
]
