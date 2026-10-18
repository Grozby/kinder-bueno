"""Command-line interface: `navigator <command>`."""

import typer

from navigator import db
from navigator.settings import get_settings
from navigator.sources import load_sources

app = typer.Typer(no_args_is_help=True)


@app.command("init-db")
def init_db() -> None:
    """Create the schema and register sources from config."""
    settings = get_settings()
    sources = load_sources(settings.sources_file)
    with db.connect(settings.database_url) as conn:
        db.init_db(conn, sources)
    typer.echo(f"Schema ready. Sources: {', '.join(s.id for s in sources.sources)}")


@app.command()
def stats() -> None:
    """Show counts per source."""
    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        rows = db.stats(conn)
    typer.echo(f"{'source':<10}{'pages':>8}{'chunks':>8}{'entities':>10}{'claims':>8}")
    for source_id, pages, chunks, entities, claims in rows:
        typer.echo(f"{source_id:<10}{pages:>8}{chunks:>8}{entities:>10}{claims:>8}")


if __name__ == "__main__":
    app()
