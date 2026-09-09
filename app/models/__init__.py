"""Import all models so Flask-Migrate discovers their metadata."""

from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.lead import Lead
from app.models.message import Message
from app.models.vehicle import Vehicle

__all__ = ["Conversation", "Customer", "Lead", "Message", "Vehicle"]
