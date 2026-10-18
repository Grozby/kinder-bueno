"""Command-line interface: `navigator <command>`."""

import asyncio
import logging

import typer

from navigator import db
from navigator.crawl import crawl_source
from navigator.settings import get_settings
from navigator.sources import load_sources

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Log every fetched URL.")) -> None:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)


@app.command("init-db")
def init_db() -> None:
    """Create the schema and register sources from config."""
    settings = get_settings()
    sources = load_sources(settings.sources_file)
    with db.connect(settings.database_url) as conn:
        db.init_db(conn, sources)
    typer.echo(f"Schema ready. Sources: {', '.join(s.id for s in sources.sources)}")


@app.command()
def crawl(
    source: str | None = typer.Option(None, help="Source id. Default: all sources."),
    max_pages: int | None = typer.Option(None, help="Override max_pages from config."),
) -> None:
    """Crawl and clean pages, then replace the stored pages of each crawled source."""
    settings = get_settings()
    sources = load_sources(settings.sources_file)
    selected = [sources.get(source)] if source else sources.sources

    async def run() -> list:
        # Sources live on different hosts, so they can be crawled in parallel.
        return await asyncio.gather(*(crawl_source(s, sources.defaults, max_pages) for s in selected))

    results = asyncio.run(run())
    with db.connect(settings.database_url) as conn:
        db.init_db(conn, sources)
        for src, pages in zip(selected, results):
            db.replace_pages(conn, src.id, pages)
            typer.echo(f"{src.id}: stored {len(pages)} pages")


@app.command()
def stats() -> None:
    """Show counts per source."""
    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        rows = db.stats(conn)
    typer.echo(f"{'source':<10}{'pages':>8}{'chunks':>8}{'entities':>10}{'claims':>8}")
    for source_id, pages, chunks, entities, claims in rows:
        typer.echo(f"{source_id:<10}{pages:>8}{chunks:>8}{entities:>10}{claims:>8}")


@app.command()
def embed(source: str | None = typer.Option(None, help="Source id. Default: all sources.")) -> None:
    """Chunk pages, embed the chunks and replace the stored chunks of each source."""
    import time

    from navigator import chunks_db
    from navigator.chunk import chunk_page
    from navigator.embed import embed_documents

    settings = get_settings()
    sources = load_sources(settings.sources_file)
    selected = [sources.get(source)] if source else sources.sources
    with chunks_db.connect(settings.database_url) as conn:
        for src in selected:
            start = time.perf_counter()
            rows = [
                (page_id, i, text)
                for page_id, title, page_text in chunks_db.pages(conn, src.id)
                for i, text in enumerate(chunk_page(title, page_text))
            ]
            vectors = embed_documents([text for _, _, text in rows], show_progress=True)
            chunks_db.replace_chunks(conn, src.id, [(*row, vec) for row, vec in zip(rows, vectors)])
            typer.echo(f"{src.id}: stored {len(rows)} chunks in {time.perf_counter() - start:.1f}s")


@app.command("search-chunks")
def search_chunks(query: str, k: int = typer.Option(10, help="Number of chunks to show.")) -> None:
    """Debug: show the top chunks for a query with page URL and score."""
    from navigator import chunks_db
    from navigator.search import search_chunks as run_search

    settings = get_settings()
    with chunks_db.connect(settings.database_url) as conn:
        hits = run_search(conn, query)[:k]
    for i, hit in enumerate(hits, start=1):
        sim = f"{hit.similarity:.3f}" if hit.similarity is not None else "  -  "
        snippet = " ".join(hit.text.split())[:120]
        typer.echo(f"{i:>2}. rrf={hit.score:.4f} sim={sim} {hit.url}\n    {snippet}")


if __name__ == "__main__":
    app()
