"""PostgreSQL integration evidence for Phase 2 import and snapshot transactions."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest
from flask_migrate import upgrade
from sqlalchemy import func, select, text

from app.extensions import db
from app.models.car import Car
from app.models.conversation import ConversationSession
from app.models.recommendation import RecommendationSnapshot, RecommendationSnapshotItem
from app.services.catalog_import_service import CatalogImportService
from app.services.recommendation_service import (
    RecommendationService,
    VisibleRecommendationError,
)

DATASET = Path(__file__).parents[2] / "data" / "egypt_cars_demo_100_balanced.csv"


def _dataset_rows() -> list[dict[str, str]]:
    with DATASET.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _truncate_phase2_tables() -> None:
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


def test_official_catalog_import_counts_normalization_and_idempotency(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_phase2_tables()
        service = CatalogImportService(db.session)
        rows = _dataset_rows()
        expected_rows = len(rows)
        expected_new = sum(row["condition"].strip().casefold() == "new" for row in rows)
        expected_used = sum(row["condition"].strip().casefold() == "used" for row in rows)
        preserved_source_id = rows[0]["source_id"]

        first = service.import_file(DATASET)
        preserved_id = db.session.scalar(
            select(Car.id).where(Car.source_id == preserved_source_id)
        )

        assert expected_rows == 100
        assert first.file_rows == expected_rows
        assert first.inserted == expected_rows
        assert first.updated == first.unchanged == first.rejected == 0
        assert db.session.scalar(select(func.count()).select_from(Car)) == expected_rows
        assert db.session.scalar(select(func.count()).where(Car.condition == "new")) == expected_new
        assert db.session.scalar(select(func.count()).where(Car.condition == "used")) == expected_used
        assert expected_new + expected_used == expected_rows
        assert (
            db.session.scalar(
                select(func.count()).where(Car.condition == "new", Car.mileage_km.is_(None))
            )
            == 0
        )
        assert (
            db.session.scalar(
                select(func.count()).where(Car.condition == "new", Car.mileage_km == 0)
            )
            == expected_new
        )
        duplicate_groups = db.session.execute(
            select(Car.source, Car.source_id)
            .group_by(Car.source, Car.source_id)
            .having(func.count() > 1)
        ).all()
        assert duplicate_groups == []

        second = service.import_file(DATASET)
        assert second.inserted == second.updated == second.rejected == 0
        assert second.unchanged == expected_rows
        assert (
            db.session.scalar(select(Car.id).where(Car.source_id == preserved_source_id))
            == preserved_id
        )
        _truncate_phase2_tables()


def test_postgres_snapshot_sequence_and_atomic_failure(pg_app):
    with pg_app.app_context():
        upgrade()
        _truncate_phase2_tables()
        cars = [
            Car(
                brand="Toyota",
                model="Corolla",
                year=2025,
                condition="new",
                price_egp=Decimal("1300000"),
                mileage_km=0,
                source="phase2-pg",
                source_id="active",
            ),
            Car(
                brand="Kia",
                model="Sportage",
                year=2024,
                condition="used",
                price_egp=Decimal("1700000"),
                mileage_km=20000,
                source="phase2-pg",
                source_id="inactive",
                active=False,
            ),
        ]
        conversation = ConversationSession()
        db.session.add_all([*cars, conversation])
        db.session.commit()
        service = RecommendationService(db.session)

        first = service.create_visible_snapshot(conversation.id, [cars[0].id])
        second = service.create_visible_snapshot(conversation.id, [cars[0].id])
        db.session.refresh(first)
        assert first.status == "superseded"
        assert second.sequence_no == 2

        with pytest.raises(VisibleRecommendationError):
            service.create_visible_snapshot(conversation.id, [cars[0].id, cars[1].id])

        db.session.refresh(conversation)
        assert conversation.active_recommendation_snapshot_id == second.id
        assert db.session.scalar(select(func.count()).select_from(RecommendationSnapshot)) == 2
        _truncate_phase2_tables()


def test_postgres_snapshot_mid_write_failure_rolls_back_partial_state(pg_app, monkeypatch):
    """A failure after the snapshot row flush must leave the prior visible state intact."""
    with pg_app.app_context():
        upgrade()
        _truncate_phase2_tables()
        session = db.session()
        cars = [
            Car(
                brand="Toyota",
                model="Corolla",
                year=2025,
                condition="new",
                price_egp=Decimal("1300000"),
                mileage_km=0,
                source="phase2-pg-mid-write",
                source_id="first",
            ),
            Car(
                brand="Kia",
                model="Sportage",
                year=2025,
                condition="new",
                price_egp=Decimal("1700000"),
                mileage_km=0,
                source="phase2-pg-mid-write",
                source_id="second",
            ),
        ]
        conversation = ConversationSession()
        session.add_all([*cars, conversation])
        session.commit()
        service = RecommendationService(session)
        baseline = service.create_visible_snapshot(conversation.id, [cars[0].id])

        original_flush = session.flush
        flush_calls = 0

        def fail_on_item_flush(*args, **kwargs):
            nonlocal flush_calls
            flush_calls += 1
            if flush_calls == 2:
                raise RuntimeError("simulated snapshot item flush failure")
            return original_flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", fail_on_item_flush)

        with pytest.raises(RuntimeError, match="simulated snapshot item flush failure"):
            service.create_visible_snapshot(conversation.id, [cars[0].id, cars[1].id])

        session.expire_all()
        persisted_conversation = session.get(ConversationSession, conversation.id)
        persisted_baseline = session.get(RecommendationSnapshot, baseline.id)
        assert persisted_conversation.active_recommendation_snapshot_id == baseline.id
        assert persisted_baseline.status == "active"
        assert session.scalar(select(func.count()).select_from(RecommendationSnapshot)) == 1
        assert session.scalar(select(func.count()).select_from(RecommendationSnapshotItem)) == 1
        _truncate_phase2_tables()
