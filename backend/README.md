# Backend

The Python package `navigator`: crawl, extraction, search, the case board API and the evals. Run its commands
from this folder (`cd backend && uv run navigator …`, `uv run pytest`); the `.env` at the repo root is read
from here too. Setup, pipeline order and tests: the [README](../README.md) at the repo root.

- `src/navigator/`: the package
  - `core/`: settings, `sources.yaml` loading, the database (`core/schema.sql`), the LLM client and embeddings
  - `ingest/`: the pipeline from crawl to judge, the crawl rules and the pages list
  - `search/`: chunk search, ranking, results, the "why" text and the chat agent
  - `cases/`: the case board: analysis, references, pitch and documents
  - `evaluation/`: `navigator eval` and `case-eval`
  - `api/`: the HTTP API: `app`, `deps` and one router per area in `routes/`
  - `models.py`: the API contract, which `frontend/src/api/types.ts` mirrors
  - `cli.py`: the `navigator` command
- `tests/`: unit tests; `tests/integration/` starts the whole stack in Docker (`uv run pytest -m integration`)
- `config/sources.yaml`: the crawled sources
- `eval/`: gold sets, example cases and the reports `navigator eval` and `case-eval` write
