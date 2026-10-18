# Research & Expertise Navigator

Find researchers, units, projects and infrastructure in the Bern research ecosystem, with every fact
linked to a quote on a public page. The build plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Setup

```bash
cp .env.example .env          # then set KEERA_API_KEY
docker compose up -d db       # Postgres 16 + pgvector
uv sync
uv run navigator init-db      # schema + sources from config/sources.yaml
```

## Pipeline

Run the steps in this order, for all sources or one source with `--source ID`:

```bash
uv run navigator crawl        # crawl + clean pages into `page`
uv run navigator embed        # chunk + embed pages into `chunk` (bge-m3, ~2.3 GB download on first run)
uv run navigator stats        # pages and chunks per source
```

**After every `crawl`, run `embed` again for the same source.** `crawl` replaces a source's pages, and
deleting a page also deletes its chunks, so a re-crawled source has no chunks and does not show up in
search until it is embedded again:

```bash
uv run navigator crawl --source dcb
uv run navigator embed --source dcb
```

## Debugging search

```bash
uv run navigator search-chunks "continuous glucose monitoring" --k 10
uv run navigator search-chunks "Herzklappen" --expand   # add Apertus search terms (needs KEERA_API_KEY)
```

Prints the top chunks (keyword + semantic search, fused with RRF) with page URL and score.
With `--expand` it first prints the English and German search terms from Apertus.

## Evaluation

```bash
uv run navigator eval             # 9 gold queries (eval/gold.yaml) through the /api/search pipeline
uv run navigator eval --no-expand --no-judge  # no gateway needed
```

Prints the plan 10.2 metrics (recall@10, phrasing overlap, traceability, field fill, coverage, drop rate,
judged precision@10) and saves them to `eval/report.md`. The eval judge's verdicts and reasons go to
`eval/judge_log.jsonl` for spot checks. Re-run it after every change to extraction, resolve or ranking.

## Tests

```bash
uv run pytest -q              # database tests are skipped when Postgres is not running
```
