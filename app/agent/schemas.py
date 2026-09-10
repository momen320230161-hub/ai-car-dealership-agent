"""Validated contracts used by the dealership agent."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


Intent = Literal["vehicle_search", "knowledge", "mixed", "general", "unsupported"]
Language = Literal["en", "ar"]


class VehicleFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brands: list[str] = Field(default_factory=list, max_length=10)
    models: list[str] = Field(default_factory=list, max_length=10)
    condition: Literal["new", "used"] | None = None
    min_year: int | None = Field(default=None, ge=1900, le=2100)
    max_year: int | None = Field(default=None, ge=1900, le=2100)
    min_price_egp: int | None = Field(default=None, ge=0)
    max_price_egp: int | None = Field(default=None, ge=0)
    fuel_types: list[str] = Field(default_factory=list, max_length=10)
    transmission_types: list[str] = Field(default_factory=list, max_length=10)
    body_types: list[str] = Field(default_factory=list, max_length=10)
    max_kilometers: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self):
        if self.min_year is not None and self.max_year is not None and self.min_year > self.max_year:
            raise ValueError("min_year cannot exceed max_year")
        if self.min_price_egp is not None and self.max_price_egp is not None and self.min_price_egp > self.max_price_egp:
            raise ValueError("min_price_egp cannot exceed max_price_egp")
        for field in ("brands", "models", "fuel_types", "transmission_types", "body_types"):
            values = [value.strip() for value in getattr(self, field) if value and value.strip()]
            setattr(self, field, list(dict.fromkeys(values)))
        return self


class RequestAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    needs_vehicle_search: bool
    needs_knowledge: bool
    vehicle_filters: VehicleFilters = Field(default_factory=VehicleFilters)
    knowledge_query: str | None = Field(default=None, max_length=2000)
    language: Language

    @model_validator(mode="after")
    def validate_routing_flags(self):
        expected = {
            "vehicle_search": (True, False),
            "knowledge": (False, True),
            "mixed": (True, True),
            "general": (False, False),
            "unsupported": (False, False),
        }[self.intent]
        if (self.needs_vehicle_search, self.needs_knowledge) != expected:
            raise ValueError("routing flags must match intent")
        if self.needs_knowledge and not self.knowledge_query:
            raise ValueError("knowledge_query is required for knowledge retrieval")
        return self


class VehicleResult(BaseModel):
    id: UUID
    brand: str
    model: str
    year: int
    condition: str
    price_egp: int
    kilometers: int | None
    fuel_type: str | None
    transmission_type: str
    body_type: str | None
    trim: str | None
    color: str | None


class AgentResult(BaseModel):
    conversation_id: UUID
    intent: Intent
    language: Language
    response: str
    vehicle_results: list[VehicleResult] = Field(default_factory=list)
    knowledge_sources: list[dict] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
