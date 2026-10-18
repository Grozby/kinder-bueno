"""Command-line interface: `navigator <command>`."""

import asyncio
import logging

import typer

from navigator import db
from collections import Counter

from navigator.crawl import crawl_source
from navigator.extract import extract_pages, reverify as reverify_rows
from navigator.llm import LLM
from navigator.resolve import resolve as run_resolve
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
def extract(
    source: str | None = typer.Option(None, help="Source id. Default: all sources."),
    limit: int | None = typer.Option(None, help="Only the first N pages (for testing)."),
    url_like: str | None = typer.Option(
        None, help="Only pages whose URL matches this SQL LIKE pattern, e.g. '%/aihn/group_members/%'."
    ),
    resolve_after: bool = typer.Option(
        True, "--resolve/--no-resolve", help="Run resolve afterwards (rebuilds entities, claims, relations)."
    ),
    judge_after: bool = typer.Option(
        True, "--judge/--no-judge", help="Run the claim judge after resolve (skipped when JUDGE_ENABLED=false)."
    ),
) -> None:
    """Extract claims and relations with Apertus, verify quotes, store raw results, then resolve and judge.
    Only the selected pages' raw rows are replaced; resolve rebuilds from all raw rows."""
    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        pages = db.pages_for_extraction(conn, source, limit, url_like)
        if not pages:
            typer.echo("No pages match.")
            raise typer.Exit(1)
        model = settings.extract_model or settings.llm_model
        typer.echo(f"Extracting {len(pages)} pages with {model} (concurrency {settings.llm_concurrency})...")
        results = asyncio.run(extract_pages(LLM(settings, settings.extract_model), pages))
        db.replace_raw_extractions(conn, results)
        _print_extraction_report(results)
        if resolve_after:
            # Resolve rebuilds the claim table, so judge verdicts are reset: run the judge after it.
            typer.echo("Resolving...")
            for name, n in sorted(run_resolve(conn).items()):
                typer.echo(f"  {name:<26}{n:>6}")
            if judge_after and settings.judge_enabled:
                _run_judge(conn, settings, source)


@app.command()
def reverify(
    resolve_after: bool = typer.Option(True, "--resolve/--no-resolve", help="Run resolve afterwards."),
) -> None:
    """Re-run the verification rules on stored raw rows (no LLM calls), e.g. after a rule change."""
    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        rows = db.raw_rows_for_reverify(conn)
        claim_updates, relation_updates = reverify_rows(rows)
        db.update_raw_verification(conn, claim_updates, relation_updates)
        for label, updates in (("claims", claim_updates), ("relations", relation_updates)):
            ok = sum(u[0] for u in updates)
            reasons = Counter(u[2] for u in updates if not u[0])
            typer.echo(f"{label}: {ok} / {len(updates)} verified; rejected: {dict(reasons.most_common())}")
        if resolve_after:
            typer.echo("Resolving...")
            for name, n in sorted(run_resolve(conn).items()):
                typer.echo(f"  {name:<26}{n:>6}")
            typer.echo("Resolve reset the judge verdicts: run `navigator judge` to judge the claims again.")


def _print_extraction_report(results: list) -> None:
    claims = [c for r in results for c in r.claims]
    relations = [x for r in results for x in r.relations]
    failed = [r for r in results if r.error]
    ok = sum(c.verified for c in claims)
    typer.echo(f"pages: {len(results)} ({len(failed)} with LLM errors)")
    typer.echo(f"claims: {len(claims)}, verified {ok} ({ok / max(len(claims), 1):.0%})")
    by_field = Counter((c.item.field, c.verified) for c in claims)
    for f in sorted({c.item.field for c in claims}):
        typer.echo(f"  {f:<12} {by_field[(f, True)]:>4} verified / {by_field[(f, True)] + by_field[(f, False)]:>4}")
    rel_ok = sum(x.verified for x in relations)
    typer.echo(f"relations: {len(relations)}, verified {rel_ok}")
    typer.echo(f"items dropped by schema validation: {sum(r.dropped for r in results)}")
    reasons = Counter(c.fail_reason for c in claims + relations if not c.verified)
    for reason, n in reasons.most_common():
        typer.echo(f"  rejected: {reason} ({n})")


@app.command()
def stats() -> None:
    """Show counts per source."""
    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        rows = db.stats(conn)
        judge_rows = db.judge_counts(conn)
    typer.echo(f"{'source':<10}{'pages':>8}{'chunks':>8}{'entities':>10}{'claims':>8}")
    for source_id, pages, chunks, entities, claims in rows:
        typer.echo(f"{source_id:<10}{pages:>8}{chunks:>8}{entities:>10}{claims:>8}")
    _print_judge_counts(judge_rows)


def _print_judge_counts(rows: list[tuple]) -> None:
    """Claim judge verdicts (plan 7.8) per source, for claims and relations."""
    if not rows:
        return
    verdicts = ("supported", "partial", "unsupported", "not judged")
    typer.echo(f"\njudge     {'':<10}" + "".join(f"{v:>13}" for v in verdicts))
    table: dict[tuple, dict] = {}
    for source_id, kind, verdict, n in rows:
        table.setdefault((source_id, kind), {})[verdict] = n
    for (source_id, kind), counts in table.items():
        typer.echo(f"{source_id:<10}{kind:<10}" + "".join(f"{counts.get(v, 0):>13}" for v in verdicts))


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
def search_chunks(
    query: str,
    k: int = typer.Option(10, help="Number of chunks to show."),
    expand: bool = typer.Option(False, help="Add Apertus search terms (plan 8.1)."),
) -> None:
    """Debug: show the top chunks for a query with page URL and score."""
    from navigator import chunks_db
    from navigator.expand import Expansion, expand_query
    from navigator.search import search_chunks as run_search

    settings = get_settings()
    expansion = asyncio.run(expand_query(LLM(settings), query)) if expand else Expansion()
    if expand:
        typer.echo(f"en: {', '.join(expansion.en) or '-'}\nde: {', '.join(expansion.de) or '-'}\n")
    with chunks_db.connect(settings.database_url) as conn:
        hits = run_search(conn, query, expansion.terms)[:k]
    for i, hit in enumerate(hits, start=1):
        sim = f"{hit.similarity:.3f}" if hit.similarity is not None else "  -  "
        snippet = " ".join(hit.text.split())[:120]
        typer.echo(f"{i:>2}. rrf={hit.score:.4f} sim={sim} {hit.url}\n    {snippet}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8000, help="Port."),
) -> None:
    """Start the HTTP API (one worker)."""
    import uvicorn

    uvicorn.run("navigator.api:app", host=host, port=port, workers=1)


@app.command()
def resolve() -> None:
    """Merge verified raw extractions into entities, claims and relations (re-runnable)."""
    from navigator.resolve import resolve as run_resolve

    settings = get_settings()
    with db.connect(settings.database_url) as conn:
        counts = run_resolve(conn)
    for name, n in sorted(counts.items()):
        typer.echo(f"{name:<26}{n:>6}")
    typer.echo("Resolve reset the judge verdicts: run `navigator judge` to judge the claims again.")


@app.command("eval")
def evaluate(
    expand: bool = typer.Option(True, help="Use query expansion, like /api/search."),
    judge: bool = typer.Option(True, help="Run the eval judge [PoC] for judged precision@10 (plan 10.3)."),
    gold: str = typer.Option("eval/gold.yaml", help="Gold set (plan 10.1)."),
    out: str = typer.Option("eval/report.md", help="Where to save the Markdown report."),
    judge_log: str = typer.Option("eval/judge_log.jsonl", help="Where to save the eval judge verdicts."),
) -> None:
    """Run the gold queries and report the plan 10.2 metrics (stdout and eval/report.md)."""
    import json
    from pathlib import Path

    from navigator import chunks_db
    from navigator.evaluate import load_gold, run

    settings = get_settings()
    with chunks_db.connect(settings.database_url) as conn:
        text, verdicts = run(conn, lambda: LLM(settings), load_gold(Path(gold)), expand=expand, judge=judge)
    Path(out).write_text(text)
    typer.echo(text)
    typer.echo(f"Saved to {out}")
    if judge:
        Path(judge_log).write_text("".join(json.dumps(v, ensure_ascii=False) + "\n" for v in verdicts))
        typer.echo(f"Saved {len(verdicts)} judge verdicts to {judge_log}")


@app.command()
def ingest(
    source: str | None = typer.Option(None, help="Source id. Default: all sources."),
    max_pages: int | None = typer.Option(None, help="Override max_pages from config (crawl)."),
) -> None:
    """Whole pipeline: init-db → crawl → embed → extract → resolve → judge (plan 11)."""
    init_db()
    crawl(source=source, max_pages=max_pages)
    embed(source=source)
    extract(source=source, limit=None, url_like=None, resolve_after=True, judge_after=True)
    stats()


def _run_judge(conn, settings, source: str | None) -> None:
    from navigator.judge import run_judge

    model = settings.judge_model or settings.llm_model
    typer.echo(f"Judging claims with {model}...")
    counts = run_judge(conn, LLM(settings, settings.judge_model), source)
    typer.echo(f"  pages: {counts.pop(('pages', 'judged'), 0)}")
    for (table, verdict), n in sorted(counts.items()):
        typer.echo(f"  {table:<9}{verdict:<13}{n:>6}")


@app.command()
def judge(source: str | None = typer.Option(None, help="Source id. Default: all sources.")) -> None:
    """Judge whether each quote supports its claim (plan 7.8); "unsupported" claims are then hidden.
    Run it after resolve: `extract`, `reverify` and `resolve` rebuild the claims and reset the verdicts."""
    settings = get_settings()
    if not settings.judge_enabled:
        typer.echo("JUDGE_ENABLED=false: skipped.")
        return
    with db.connect(settings.database_url) as conn:
        _run_judge(conn, settings, source)


@app.command("llm-speed")
def llm_speed(
    model: list[str] = typer.Option([], help="Model to test (repeatable). Default: the 70B and 8B models."),
) -> None:
    """Measure the gateway: time to first token and tokens/s per model (#16)."""
    from navigator.llm import measure_speed

    settings = get_settings()
    models = model or [settings.llm_model, "apertus-v1-5-8b"]
    for m in dict.fromkeys(models):
        try:
            sp = asyncio.run(measure_speed(settings, m))
            first = f"{sp.first_token_s:.1f}s" if sp.first_token_s is not None else "-"
            typer.echo(f"{m:<28} first token {first:>6}   {sp.tokens:>4} tokens in {sp.seconds:5.1f}s   "
                       f"{sp.tokens_per_s:6.1f} tokens/s")
        except Exception as e:  # report and go on with the next model
            typer.echo(f"{m:<28} failed: {str(e)[:120]}")


@app.command("case-eval")
def case_eval(
    gold: str = typer.Option("eval/cases.yaml", help="Example business models with expected matches (#73)."),
    out: str = typer.Option("eval/case_report.md", help="Where to save the Markdown report."),
) -> None:
    """Run the case analysis read-only on the example PDFs and compare with the expected matches (#73)."""
    from pathlib import Path

    from navigator import chunks_db
    from navigator.analysis import read_case, rerank
    from navigator.case_eval import evaluate_case, load_cases, report
    from navigator.embed import embed_documents, embed_query

    settings = get_settings()
    with chunks_db.connect(settings.database_url) as conn:
        outcomes = [  # one LLM client per asyncio.run: the client is bound to its event loop
            evaluate_case(conn, case, lambda text: asyncio.run(read_case(LLM(settings), text)), embed_query,
                          embed_documents, rerank)
            for case in load_cases(Path(gold))
        ]
    text = report(outcomes)
    Path(out).write_text(text)
    typer.echo(text)
    typer.echo(f"Saved to {out}")


if __name__ == "__main__":
    app()
