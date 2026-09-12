"""PostgreSQL integration tests for production-specific model behavior."""

from decimal import Decimal

import pytest
from flask_migrate import upgrade
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.message import ChatMessage
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem


def _truncate_phase1_tables() -> None:
    db.session.execute(
        text(
            """
            TRUNCATE TABLE
                recommendation_snapshot_items,
                sales_leads,
                test_drive_requests,
                chat_messages,
                recommendation_snapshots,
                conversation_sessions,
                knowledge_documents,
                cars
            RESTART IDENTITY CASCADE
            """
        )
    )
    db.session.commit()


def test_postgres_model_persistence_and_snapshot_session_isolation(pg_app):
    """Verify JSONB/UUID persistence and the cross-session active-snapshot guard."""
    with pg_app.app_context():
        upgrade()
        _truncate_phase1_tables()

        car = Car(
            brand="MG",
            model="ZS",
            year=2024,
            condition="new",
            price_egp=Decimal("1200000.00"),
            source="integration-test",
            source_id="pg-car-1",
            data_quality_metadata={"verified": True},
        )
        owner_session = ConversationSession(preferences={"body_type": "SUV"})
        other_session = ConversationSession()
        db.session.add_all([car, owner_session, other_session])
        db.session.commit()

        snapshot = RecommendationSnapshot(
            session_id=owner_session.id,
            sequence_no=1,
            criteria={"body_type": "SUV"},
        )
        db.session.add(snapshot)
        db.session.commit()

        db.session.add_all(
            [
                RecommendationSnapshotItem(
                    snapshot_id=snapshot.id,
                    position=1,
                    car_id=car.id,
                ),
                ChatMessage(
                    session_id=owner_session.id,
                    role="user",
                    content="عايز SUV",
                ),
            ]
        )
        owner_session.active_recommendation_snapshot_id = snapshot.id
        db.session.commit()

        assert owner_session.preferences == {"body_type": "SUV"}
        assert car.data_quality_metadata == {"verified": True}
        assert owner_session.active_recommendation_snapshot_id == snapshot.id

        other_session.active_recommendation_snapshot_id = snapshot.id
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        db.session.refresh(other_session)
        assert other_session.active_recommendation_snapshot_id is None

        _truncate_phase1_tables()
