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
