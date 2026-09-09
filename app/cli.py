"""Flask commands for operational database tasks."""

from pathlib import Path

import click

from app.services.vehicle_importer import import_vehicles


def register_commands(app):
    @app.cli.command("import-vehicles")
    @click.argument("csv_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def import_vehicles_command(csv_path: Path):
        """Validate and import the approved vehicle CSV by stable source_id."""
        result = import_vehicles(csv_path)
        click.echo(
            "Vehicle import complete: "
            f"attempted={result.attempted} inserted={result.inserted} "
            f"updated={result.updated} skipped={result.skipped} rejected={result.rejected}"
        )

    @app.cli.group("knowledge")
    def knowledge_group():
        """Manage unstructured dealership knowledge."""

    @knowledge_group.command("add")
    @click.option("--title", required=True)
    @click.option("--category")
    @click.option("--source-type")
    @click.option("--source-reference")
    @click.option("--file", "content_file", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def knowledge_add(title, category, source_type, source_reference, content_file):
        """Create and embed a document from a text or Markdown file."""
        from app.services.knowledge import KnowledgeService

        document = KnowledgeService().create_document(
            title=title, content=content_file.read_text(encoding="utf-8"), category=category,
            source_type=source_type or "file", source_reference=source_reference or str(content_file),
        )
        click.echo(f"Created knowledge document {document.id} with {len(document.chunks)} chunks")

    @knowledge_group.command("update")
    @click.argument("document_id")
    @click.option("--title")
    @click.option("--category")
    @click.option("--source-type")
    @click.option("--source-reference")
    @click.option("--file", "content_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    def knowledge_update(document_id, title, category, source_type, source_reference, content_file):
        """Update metadata and optionally replace document content atomically."""
        from app.services.knowledge import KnowledgeService

        changes = {
            key: value for key, value in {
                "title": title, "category": category, "source_type": source_type,
                "source_reference": source_reference,
                "content": content_file.read_text(encoding="utf-8") if content_file else None,
            }.items() if value is not None
        }
        if not changes:
            raise click.UsageError("provide at least one update option")
        document = KnowledgeService().update_document(document_id, **changes)
        click.echo(f"Updated knowledge document {document.id}")

    @knowledge_group.command("delete")
    @click.argument("document_id")
    def knowledge_delete(document_id):
        """Delete one explicitly identified document and its chunks."""
        from app.services.knowledge import KnowledgeService

        KnowledgeService().delete_document(document_id)
        click.echo(f"Deleted knowledge document {document_id}")

    @knowledge_group.command("list")
    def knowledge_list():
        """List knowledge documents without embeddings or full content."""
        from app.services.knowledge import KnowledgeService

        for document in KnowledgeService().list_documents():
            click.echo(f"{document.id}\t{document.title}\t{document.category or '-'}\t{len(document.chunks)} chunks")

    @knowledge_group.command("search")
    @click.argument("query")
    @click.option("--top-k", type=int)
    @click.option("--category")
    @click.option("--min-similarity", type=float)
    def knowledge_search(query, top_k, category, min_similarity):
        """Search knowledge semantically and print concise provenance."""
        from app.services.retrieval import RetrievalService

        results = RetrievalService().search_knowledge(
            query, top_k=top_k, category=category, min_similarity=min_similarity
        )
        for result in results:
            excerpt = result.content.replace("\n", " ")[:160]
            click.echo(
                f"{result.similarity:.4f}\t{result.document_title}\t"
                f"{result.category or '-'}\t{result.source_reference or '-'}\t{excerpt}"
            )
