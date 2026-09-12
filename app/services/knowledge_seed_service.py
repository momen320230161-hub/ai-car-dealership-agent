"""Idempotent, approved-file seeding for production knowledge documents."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.models.knowledge import KnowledgeDocument
from app.services.knowledge_service import KnowledgeService, KnowledgeServiceError


class KnowledgeSeedError(RuntimeError):
    """Controlled validation or synchronization failure for knowledge seed files."""


@dataclass(frozen=True, slots=True)
class KnowledgeSeedReport:
    version: str
    total: int
    created: int
    updated: int
    reindexed: int
    unchanged: int
    failed: int
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SeedDocument:
    id: uuid.UUID
    title: str
    category: str
    content: str
    active: bool


class KnowledgeSeedService:
    """Synchronize an approved JSON seed through the managed KnowledgeService."""

    APPROVED_STATUS = "approved_for_seed"

    def __init__(self, knowledge_service: KnowledgeService):
        self.knowledge_service = knowledge_service

    def seed_file(self, path: str | Path) -> KnowledgeSeedReport:
        version, seed_documents = self._load_seed(path)
        existing = self._existing_by_id()

        created = 0
        updated = 0
        reindexed = 0
        unchanged = 0
        errors: list[str] = []

        for seed_document in seed_documents:
            try:
                document = existing.get(seed_document.id)
                if document is None:
                    document = self.knowledge_service.create_document(
                        document_id=seed_document.id,
                        title=seed_document.title,
                        category=seed_document.category,
                        content=seed_document.content,
                        active=seed_document.active,
                    )
                    existing[seed_document.id] = document
                    created += 1
                    continue

                content_changed = document.content != seed_document.content
                metadata_changed = (
                    document.title != seed_document.title
                    or document.category != seed_document.category
                    or document.active != seed_document.active
                )
                if content_changed or metadata_changed:
                    self.knowledge_service.update_document(
                        document.id,
                        title=seed_document.title,
                        category=seed_document.category,
                        content=seed_document.content,
                        active=seed_document.active,
                    )
                    updated += 1
                    continue

                needs_reindex = (
                    document.index_status != "indexed"
                    or document.indexed_version != document.content_version
                    or document.embedding_model != self.knowledge_service.provider.model_name
                )
                if needs_reindex:
                    self.knowledge_service.reindex_document(document.id)
                    reindexed += 1
                else:
                    unchanged += 1
            except (KnowledgeServiceError, ValueError) as exc:
                errors.append(f"{seed_document.id} {seed_document.title}: {exc}")

        return KnowledgeSeedReport(
            version=version,
            total=len(seed_documents),
            created=created,
            updated=updated,
            reindexed=reindexed,
            unchanged=unchanged,
            failed=len(errors),
            errors=errors,
        )

    def _existing_by_id(self) -> dict[uuid.UUID, KnowledgeDocument]:
        return {
            document.id: document
            for document in self.knowledge_service.repository.list_documents()
        }

    def _load_seed(self, path: str | Path) -> tuple[str, list[SeedDocument]]:
        seed_path = Path(path)
        try:
            payload = json.loads(seed_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise KnowledgeSeedError(f"Knowledge seed file could not be read: {seed_path}") from exc
        except json.JSONDecodeError as exc:
            raise KnowledgeSeedError("Knowledge seed file is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise KnowledgeSeedError("Knowledge seed root must be a JSON object")
        version = self._required_text(payload.get("version"), "version")
        if payload.get("status") != self.APPROVED_STATUS:
            raise KnowledgeSeedError(
                f"Knowledge seed status must be {self.APPROVED_STATUS!r} before live seeding"
            )
        raw_documents = payload.get("documents")
        if not isinstance(raw_documents, list) or not raw_documents:
            raise KnowledgeSeedError("Knowledge seed must contain a non-empty documents list")

        documents: list[SeedDocument] = []
        ids: set[uuid.UUID] = set()
        title_categories: set[tuple[str, str]] = set()
        for index, raw_document in enumerate(raw_documents, start=1):
            if not isinstance(raw_document, dict):
                raise KnowledgeSeedError(f"Knowledge seed document #{index} must be an object")
            document_id = self._required_uuid(
                raw_document.get("id"), f"documents[{index}].id"
            )
            title = self._required_text(raw_document.get("title"), f"documents[{index}].title")
            category = self._required_text(
                raw_document.get("category"), f"documents[{index}].category"
            ).casefold()
            content = self._required_text(
                raw_document.get("content"), f"documents[{index}].content"
            )
            active = raw_document.get("active", True)
            if not isinstance(active, bool):
                raise KnowledgeSeedError(f"documents[{index}].active must be a boolean")
            if document_id in ids:
                raise KnowledgeSeedError(
                    f"Knowledge seed contains duplicate document id: {document_id}"
                )
            title_category = (title.casefold(), category)
            if title_category in title_categories:
                message = (
                    "Knowledge seed contains duplicate title/category identity: "
                    f"{title} [{category}]"
                )
                raise KnowledgeSeedError(message)
            ids.add(document_id)
            title_categories.add(title_category)
            documents.append(
                SeedDocument(
                    id=document_id,
                    title=title,
                    category=category,
                    content=content,
                    active=active,
                )
            )
        return version, documents

    @staticmethod
    def _required_text(value: Any, name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeSeedError(f"{name} must not be blank")
        return value.strip()

    @staticmethod
    def _required_uuid(value: Any, name: str) -> uuid.UUID:
        if not isinstance(value, str) or not value.strip():
            raise KnowledgeSeedError(f"{name} must be a UUID string")
        try:
            return uuid.UUID(value.strip())
        except ValueError as exc:
            raise KnowledgeSeedError(f"{name} must be a valid UUID") from exc
