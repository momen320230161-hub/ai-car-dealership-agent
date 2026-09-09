from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Conversation, Customer, Lead, Message, Vehicle


def vehicle(**overrides):
    values = {
        "brand": "Ford", "model": "Focus", "year": 2020, "condition": "used",
        "price_egp": 500000, "transmission_type": "Automatic", "source": "fixture",
        "source_id": "fixture-vehicle-1", "data_quality_status": "clean",
        "data_quality_metadata": {},
    }
    values.update(overrides)
    return Vehicle(**values)


def test_vehicle_constraints_and_nullable_semantics(app):
    db.session.add(vehicle(kilometers=None, engine_capacity_cc=None, powertrain_type="BEV"))
    db.session.commit()
    assert db.session.scalar(db.select(Vehicle).where(Vehicle.source_id == "fixture-vehicle-1")).kilometers is None

    db.session.add(vehicle(source_id="fixture-vehicle-2", price_egp=-1))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(vehicle(source_id="fixture-vehicle-3", condition="certified"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_source_id_is_unique(app):
    db.session.add_all([vehicle(), vehicle(brand="Toyota")])
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_customer_lead_and_conversation_relationships(app):
    customer = Customer(first_name="Amina", last_name="Ali", email="amina@example.test")
    car = vehicle()
    db.session.add_all([customer, car])
    db.session.commit()
    lead = Lead(customer=customer, vehicle=car, source="web")
    conversation = Conversation(customer=customer, lead=lead, channel="web")
    conversation.messages.append(Message(sender_type="customer", content="Is it available?"))
    db.session.add_all([lead, conversation])
    db.session.commit()
    assert customer.leads == [lead]
    assert car.leads == [lead]
    assert conversation.messages[0].sender_type == "customer"

    db.session.add(Message(conversation=conversation, sender_type="bot", content="invalid"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_lead_can_have_no_vehicle(app):
    customer = Customer(first_name="Mona", last_name="Saleh")
    db.session.add(customer)
    db.session.commit()
    db.session.add(Lead(customer=customer, source="phone", vehicle=None))
    db.session.commit()
    assert customer.leads[0].vehicle is None
