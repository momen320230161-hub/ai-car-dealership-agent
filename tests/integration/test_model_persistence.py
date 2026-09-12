"""Integration tests for multi-model workflows and cascade behaviors."""

from decimal import Decimal

from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.message import ChatMessage
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem


def test_session_cascade_deletes_messages_and_snapshots(db_session):
    """Verify that deleting a session cascades to its messages and recommendation snapshots."""
    session = ConversationSession()
    db_session.add(session)
    db_session.commit()

    car = Car(brand="MG", model="ZS", year=2023, condition="used", price_egp=Decimal("950000.00"))
    db_session.add(car)
    db_session.commit()

    msg = ChatMessage(session_id=session.id, role="user", content="What MG cars do you have?")
    snapshot = RecommendationSnapshot(session_id=session.id, sequence_no=1)
    db_session.add_all([msg, snapshot])
    db_session.commit()

    item = RecommendationSnapshotItem(snapshot_id=snapshot.id, position=1, car_id=car.id)
    db_session.add(item)
    db_session.commit()

    # Clear active references before deleting session to test cascade cleanly
    session_id = session.id
    snapshot_id = snapshot.id

    db_session.delete(session)
    db_session.commit()

    # Messages and snapshots should be deleted
    assert db_session.get(ConversationSession, session_id) is None
    assert db_session.query(ChatMessage).filter_by(session_id=session_id).count() == 0
    assert db_session.get(RecommendationSnapshot, snapshot_id) is None
    item_count = (
        db_session.query(RecommendationSnapshotItem)
        .filter_by(snapshot_id=snapshot_id)
        .count()
    )
    assert item_count == 0

    # The car itself should NOT be deleted
    assert db_session.get(Car, car.id) is not None

