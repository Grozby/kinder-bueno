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
    """Crawl and clean pages, then replace the stored pages of each crawled source.
    Rules edited in the UI (#79) replace a source's patterns in config/sources.yaml."""
    from navigator.rules import apply_blocks, with_stored

    settings = get_settings()
    sources = load_sources(settings.sources_file)
    selected = [sources.get(source)] if source else sources.sources

    async def run() -> list:
        # Sources live on different hosts, so they can be crawled in parallel.
        return await asyncio.gather(*(crawl_source(s, sources.defaults, max_pages) for s in selected))

    with db.connect(settings.database_url) as conn:
        db.init_db(conn, sources)
        conn.commit()
        selected = [with_stored(conn, s) for s in selected]
        results = asyncio.run(run())
        for src, pages in zip(selected, results):
            db.replace_pages(conn, src.id, pages)
            apply_blocks(conn, src.id, src.exclude_patterns)  # src has the stored rules
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
        model = settings.extract_model
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
def warm() -> None:
    """Download the local models (bge-m3, the case reranker) into the HuggingFace cache, so neither the first
    start nor the first case upload waits on a ~4.5 GB download."""
    from navigator.analysis import _reranker
    from navigator.embed import get_model

    typer.echo(f"Embedding model: {get_settings().embed_model}")
    get_model()
    typer.echo("Reranker: loading")
    _reranker()
    typer.echo("Models ready.")


@app.command()
def search(
    query: str,
    source: list[str] = typer.Option([], help="Source id (repeatable). Default: all sources."),
    type_: list[str] = typer.Option(
        [], "--type", help="person, unit, project or infrastructure (repeatable). Default: person and unit."
    ),
    limit: int = typer.Option(10, min=1, help="Number of results to show."),
    as_json: bool = typer.Option(False, "--json", help="Print the API's result objects."),
    explain: bool = typer.Option(True, help="Ask Apertus for the 'why' sentences, like /api/search."),
) -> None:
    """Rank entities for a query, like GET /api/search: expansion, fusion, fairness cap, explanations."""
    from typing import get_args

    from navigator import chunks_db
    from navigator.api import run_search
    from navigator.embed import embed_query
    from navigator.expand import expand_query
    from navigator.explain import explain as explain_results
    from navigator.models import EntityType

    unknown = [t for t in type_ if t not in get_args(EntityType)]
    if unknown:
        raise typer.BadParameter(f"unknown type {', '.join(unknown)}", param_hint="--type")
    settings = get_settings()

    # A new LLM per call: the client is bound to the event loop of its first asyncio.run.
    def expand(q):
        return asyncio.run(expand_query(LLM(settings), q))

    def why(q, results):
        if not explain:
            return {}
        return asyncio.run(explain_results(LLM(settings, settings.explain_model), q, results[:limit]))

    with chunks_db.connect(settings.database_url) as conn:
        found = run_search(conn, embed_query, expand, why, query, source, type_)
    found = found.model_copy(update={"results": found.results[:limit]})
    if as_json:
        typer.echo(found.model_dump_json(indent=2))
        return
    if found.expansion:
        typer.echo(f"en: {', '.join(found.expansion.en) or '-'}\nde: {', '.join(found.expansion.de) or '-'}\n")
    if found.no_result:
        typer.echo("No result.")
    for i, r in enumerate(found.results, start=1):
        typer.echo(f"{i:>2}. {r.name} ({r.type}, score {r.score:.3f})")
        if r.affiliations:
            typer.echo(f"    unit: {'; '.join(r.affiliations)}")
        typer.echo(f"    why: {r.why}")
        for ev in r.evidence:
            value = " ".join(ev.value.split())[:80]
            typer.echo(f"    - {ev.field}: {value}  {ev.url}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address."),
    port: int = typer.Option(8000, help="Port."),
    workers: int = typer.Option(1, min=1, help="Worker processes; each loads the models (~3 GB of RAM)."),
) -> None:
    """Start the HTTP API. Chats and the ingest slot are kept in Postgres (#103), so any number of workers works."""
    import uvicorn

    uvicorn.run("navigator.api:app", host=host, port=port, workers=workers)


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
    gold: str | None = typer.Option(None, help="Gold set (plan 10.1). Default: EVAL_DIR/gold.yaml."),
    out: str | None = typer.Option(None, help="Where to save the Markdown report. Default: EVAL_DIR/report.md."),
    judge_log: str | None = typer.Option(None, help="Eval judge verdicts. Default: EVAL_DIR/judge_log.jsonl."),
) -> None:
    """Run the gold queries and report the plan 10.2 metrics (stdout and eval/report.md)."""
    import json
    from pathlib import Path

    from navigator import chunks_db
    from navigator.evaluate import load_gold, run

    settings = get_settings()
    gold = gold or settings.eval_dir / "gold.yaml"
    out = out or settings.eval_dir / "report.md"
    judge_log = judge_log or settings.eval_dir / "judge_log.jsonl"
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
    gold: str | None = typer.Option(
        None, help="Example business models with expected matches (#73). Default: EVAL_DIR/cases.yaml."
    ),
    out: str | None = typer.Option(None, help="Where to save the Markdown report. Default: EVAL_DIR/case_report.md."),
) -> None:
    """Run the case analysis read-only on the example PDFs and compare with the expected matches (#73)."""
    from pathlib import Path

    from navigator import chunks_db
    from navigator.analysis import label_matches, read_case, rerank
    from navigator.case_eval import evaluate_case, load_cases, report
    from navigator.embed import embed_documents, embed_query

    settings = get_settings()
    gold = gold or settings.eval_dir / "cases.yaml"
    out = out or settings.eval_dir / "case_report.md"
    with chunks_db.connect(settings.database_url) as conn:
        outcomes = [  # one LLM client per asyncio.run: the client is bound to its event loop
            evaluate_case(conn, case, lambda text: asyncio.run(read_case(LLM(settings), text)), embed_query,
                          embed_documents, rerank,
                          lambda needs, pairs: asyncio.run(label_matches(LLM(settings), needs, pairs)))
            for case in load_cases(Path(gold))
        ]
    text = report(outcomes)
    Path(out).write_text(text)
    typer.echo(text)
    typer.echo(f"Saved to {out}")


if __name__ == "__main__":
    app()
