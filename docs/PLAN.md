# Research & Expertise Navigator — Build Plan

Hackathon: HackApertus — challenge from the Bern Economic Development Agency.
Time budget: 8 hours. Team: 2 people.
This plan is the single source of truth. An agent or a person must be able to build the prototype from this file only.

Writing rules for this file: short sentences, simple words. "MUST" means required. "SHOULD" means do it if time allows.
**[PoC]** marks proof-of-concept parts (LLM judge, chat, feedback). They are SHOULD items: build them fast and simple, and drop them first if time runs out (see section 13).

---

## 1. Goal

Build an end-to-end prototype:

```
public web pages → crawl → clean text → extract facts (with quotes) → verify quotes
→ judge claims [PoC] → store in Postgres → search (keyword + semantic)
→ structured, source-backed results in a web UI with chat refinement [PoC]
```

A user types a question like "glucose sensors". The system returns people and research units. **[PoC]** The user can then refine in a chat: "only DCB", "more like the 2nd one", "who works with her?". Each result shows:

- person name and contact (if public)
- role / function
- affiliation (department, institute, research group)
- fields of expertise
- related projects or activities
- related infrastructure or services
- one short sentence: why this result matches
- links to the original source pages

**Every fact shown MUST come from a public page and MUST link to it. The system MUST NOT invent people, roles or projects.**

### Pitch framing (for the final presentation only — do not build this)

Today: find experts in the Bern research ecosystem.
Tomorrow: the same pipeline (crawl → verified facts → search) feeds location reports for companies that want to settle in Canton Bern (suppliers, manufacturers, advisors). This is the scalability story.

### Non-goals (do NOT build)

- Business reports for companies.
- Supplier or manufacturer data.
- User accounts, login, admin UI. Chat state is per browser session only (an anonymous `session_id`), never per user.
- Free-text Q&A chat over the knowledge base. The chat only refines searches; it shows result cards, not free-text facts.
- Graph database (Neo4j). Postgres only. The schema keeps entities and relations in tables, so Neo4j can be added later.
- Full crawl of all University of Bern websites.
- Live web search at query time.

---

## 2. Success criteria (from the challenge) and how we meet them

| # | Criterion | How we meet it | How we measure it |
|---|---|---|---|
| 1 | ≥ 80% of expected experts/units in top 10 | Hybrid search + query expansion | `eval` script: recall@10 on gold set |
| 2 | Synonyms / lay terms find the same experts | Apertus query expansion + multilingual embeddings (bge-m3) | `eval` script: overlap of top 10 across 3 phrasings of the same use case |
| 3 | 100% of results link to a supporting public page, nothing invented | Every extracted fact has an exact quote; quote is checked against the stored page text; failed facts are dropped | `eval` script: share of displayed facts with a verified quote (must be 100%) |
| 4 | Structured results with all required fields (when the source has them) | Fixed extraction schema; UI card shows all fields | `eval` script: field fill rate |
| 5 | Covers UniBE, ARTORG, Diabetes Center Berne | One config block per source | `eval` script: count of pages and entities per source |
| 6 | New website can be added by config | `config/sources.yaml` + one CLI command | README section "Add a new source" |

Ethical rules from the challenge, and how we meet them:

- **Traceability:** quote verification (section 7.6). **[PoC]** An LLM judge checks that the quote supports the claim (section 7.8). Explanations and chat replies only use stored quotes (sections 8.6, 8.10).
- **Fair representation:** max 3 results per unit in the top 10 (section 8.5). No ranking boost for big institutes.
- **Accuracy:** if no good match, the UI says "No reliable source found for this query" (section 8.7).
- **Data protection (nDSG / GDPR):** only public fields, every field linked to source, no data from other places, data is replaced on every recrawl. Add a short note in the README.

---

## 3. Fixed decisions

| Topic | Decision |
|---|---|
| Language | Python 3.12, managed with `uv` (project already exists) |
| Run environment | `docker-compose`: `db`, `app` (backend API) and `frontend` services. No connection to Canton Bern networks. |
| Database | Postgres 16 with `pgvector` (Docker image `pgvector/pgvector:pg16`) |
| LLM | Apertus v1.5 70B via the Keera gateway (OpenAI-compatible API) |
| LLM model name | `apertus-v1-5-70b` for all steps, except extraction (see below). Do NOT use the `-thinking` variants (slower, extra reasoning text breaks JSON parsing). |
| Extraction model | `EXTRACT_MODEL=apertus-v1-5-8b` (kept after a measured comparison, #16). On the shared gateway, 70B dropped from ~51 to ~5 tokens/s (other teams), so a 100-page run timed out. 8B runs at ~120–160 tokens/s: 100 pages in ~10 min. Quote verification protects against 8B errors. When 70B was fast again (52.6 tokens/s, `navigator llm-speed`), a 70B run on a copy of the database was **not better** (table below), so 8B stays. |
| Embeddings | `BAAI/bge-m3` (1024 dimensions, multilingual), runs locally on CPU via `sentence-transformers`. The gateway has no embedding model. |
| Keyword search | Postgres full-text search, `simple` config (mixed German/English text) |
| UI | Vue 3 + Vite + TypeScript, PrimeVue 5, Pinia, vue-router, in `frontend/` (scaffold already in the repo). *Pending teammate review.* |
| Backend API | FastAPI + uvicorn on port 8000, **one worker** (the chat state lives in process memory). The Vite dev server proxies `/api` to it. |
| LLM judge [PoC] | Same model, `apertus-v1-5-70b`, temperature 0. It judges its own extractions, so it is **biased** (self-preference). Accepted for the PoC; say so in the pitch. No human calibration now (see section 16). |
| Chat state [PoC] | LangGraph `StateGraph` + `MemorySaver` checkpointer, `thread_id` = browser `session_id`. Later: swap to `PostgresSaver` (same Postgres). |
| Crawl size | **100 pages total** to start. Configurable. Scale up later. |
| Graph DB | Not now. Postgres tables `entity` + `relation` keep the data graph-shaped. |
| Reranker | Later (after the hackathon): `BAAI/bge-reranker-v2-m3` on top 50. Its hour-6 slot now goes to the chat [PoC]. |

### LLM endpoint facts (checked)

- Base URL: `https://gateway.keera.ch/api/v1`
- Auth: header `Authorization: Bearer $KEERA_API_KEY`
- Available models: `apertus-v1-5-70b`, `apertus-v1-5-70b-thinking`, `apertus-v1-5-8b`, `apertus-v1-5-8b-thinking`
- Test call to `apertus-v1-5-70b`: works, ~1.3 s for a short answer.
- Rate limits: none seen (16 parallel requests: all OK in 0.6 s).
- JSON mode (`response_format={"type": "json_object"}`): **works** (checked). The client still falls back to plain parsing if it is rejected.
- **Speed varies a lot** (shared gateway): 70B measured at 51 and later at 5 tokens/s; 8B at ~160 tokens/s. Check it with `navigator llm-speed` (one short streamed call per model: time to first token and tokens/s).
- **70B vs 8B extraction (2026-10-18, #16).** Same 100 pages, same eval code (after #42), each run followed by resolve and the claim judge. 70B at 52.6 tokens/s took 15 min (8B ~10 min).

  | | 8B | 70B |
  |---|---|---|
  | verified raw claims | 87% (1,484 / 1,705) | 87% (1,448 / 1,661) |
  | entities artorg / dcb / unibe | 268 / 126 / 83 | 255 / 162 / 80 |
  | recall@10 (lay-term) | **46% (47%)** | 43% (43%) |
  | field fill: affiliations / unit_topics | **100% / 78%** | 85% / 65% |
  | judged precision@10 [PoC] | **63%** | 46% |
  | judge gold agreement [PoC] | 90% | 58% (judge not reliable) |

  70B found more DCB entities but did not rank or fill better. The claim judge also failed on 25 DCB pages (empty error), so 173 DCB claims stayed unjudged. Decision: keep 8B; the bottleneck is ranking (#59), not the extraction model.
- **Long answers end in `504 Gateway Time-out`.** All calls MUST stream (`stream=True`); `llm.py` does this.
- Tool calling (OpenAI `tools` + `tool_choice: "auto"`): **works** (checked). The gateway is vLLM. Test: "Find experts on glucose sensors at DCB only." → `search(query="glucose sensors", source="dcb")`, `finish_reason: "tool_calls"`.

Python client:

```python
from openai import AsyncOpenAI
client = AsyncOpenAI(base_url=settings.llm_base_url, api_key=settings.keera_api_key)
```

### Secrets

- The API key is in `.env` as `KEERA_API_KEY`. `.env` is in `.gitignore`. NEVER commit it. NEVER print it in logs.
- Commit a `.env.example` with empty values.

---

## 4. Data sources (100 pages total)

All three sources are treated as one information ecosystem. Each source is one block in `config/sources.yaml`.

### 4.1 Facts about the sites (checked)

**ARTORG Center** — `https://www.artorg.unibe.ch/`
- University of Bern CMS. Pages end with `index_eng.html` (English), `index_ger.html` (German).
- Structure: `/research/<lab>/index_eng.html`, with sub-pages `group_members/`, `group_members/persons/<name>/`, `research/`, `facilities/`, `publications/`, `msc_thesis_projects/`, `open_positions/`.
- Example labs: `/research/msl/`, `/research/arsl/`, `/research/nrg/`. The research index is `/research/index_eng.html`.
- **Emails are hidden with JavaScript**, like: `javascript:void(location.href='mailto:'+String.fromCharCode(105,110,102,111,...))`. The cleaner MUST decode these (section 6.3).
- robots.txt disallows: `/error`, `/icons`, `/ajax_getPageContent`, `/getJSONSchema`, `*/manage`, preview URLs, `*index.html` (no language suffix), sitemaps, print pages.

**Diabetes Center Berne (DCB)** — `https://www.dcberne.com/en/`
- WordPress site. English pages under `/en/`, German under `/de/`.
- Useful pages: `/en/team/` (names, roles, "Mail" links), `/en/projects/`, `/en/focus-areas/`, `/en/offering/`, `/en/innovation/`, `/en/partners-network/`, `/en/category/reserach/` (sic — the site spells it "reserach").
- News posts are at `/en/<slug>/` (example: `/en/snaq-launches-the-first-ai-nutritionist-for-cgm-users-managing-diabetes/`).
- robots.txt disallows `/wp-admin/`, `/wp-includes/`, `/wp-content/plugins|themes|cache/`, `/feed/`, `/comments/`, `/?s=`.

**University of Bern (UniBE)** — fallback seeds (no subdomain inventory available)
- Same CMS as ARTORG (`index_eng.html`).
- Seeds: `https://www.medizin.unibe.ch/index_eng.html`, `https://www.unibe.ch/facultiesinstitutes/index_eng.html`.
- Follow links only on `*.unibe.ch`. Exclude `www.artorg.unibe.ch` (own source), and service hosts: `intern.unibe.ch`, `karriere.unibe.ch`, `teachinghub.unibe.ch`, `mediarelations.unibe.ch`, `www.ub.unibe.ch`.

### 4.2 Page budget

| Source | Max pages |
|---|---|
| ARTORG | 45 |
| DCB | 30 |
| UniBE | 25 |

Budgets live in config (`max_pages`). Scale to ~2000 total later by changing config only.

### 4.3 `config/sources.yaml`

The live file is `config/sources.yaml`. Lessons from the first crawl (already applied there):

- **Priority patterns must be narrow and anchored to the site root.** A broad pattern like `/research/` matched every page, so the whole budget went to the first 2 labs. With anchored patterns, the crawl now gets every lab overview, every member list and every service page first.
- **UniBE fallback seeds:** `www.medizin.unibe.ch` led mostly to psychiatry and admin pages. The working seeds are DBMR research programs (~40 biomedical labs, incl. cardiology), the Cardiovascular Research Cluster (`www.cvrc.unibe.ch`) and sitem-insel (`www.sitem.unibe.ch`). Hosts are an explicit allow list.
- **DCB:** paginated news listings (`/category/`, `/page/N/`) are excluded; project pages are priority.
- **ARTORG IGT** (image-guided therapy) is a *former* chair. Its member list is not linked and is not crawled on purpose (outdated people would break the accuracy rule). The surgery use case uses AIMI (surgical instrument tracking) and ARSL (surgical robotics) instead.

---

## 5. Repository layout

```
kinder-bueno/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore                 # already contains .env
├── pyproject.toml
├── README.md
├── config/
│   └── sources.yaml
├── docs/
│   └── PLAN.md                # this file
├── src/navigator/
│   ├── __init__.py
│   ├── settings.py            # pydantic-settings, reads .env
│   ├── sources.py             # load + validate sources.yaml
│   ├── db.py                  # psycopg connection, schema init
│   ├── schema.sql
│   ├── crawl.py               # fetch pages, follow links, robots.txt
│   ├── clean.py               # HTML → main text, decode emails
│   ├── chunk.py               # text → chunks
│   ├── embed.py               # bge-m3 embeddings
│   ├── llm.py                 # Apertus client, retries, JSON parsing
│   ├── extract.py             # page → claims (with quotes)
│   ├── verify.py              # quote check
│   ├── resolve.py             # merge duplicate entities
│   ├── judge.py               # [PoC] LLM judge: claim support (7.8) + eval relevance (10.3)
│   ├── search.py              # expansion, hybrid search, RRF, grouping, fairness
│   ├── explain.py             # "why it matches" sentences
│   ├── agent.py               # [PoC] LangGraph chat agent
│   ├── api.py                 # FastAPI app: /api/search, /api/chat, /api/feedback, /api/stats
│   └── cli.py                 # typer CLI
├── frontend/                  # Vue 3 + PrimeVue app (section 9)
│   ├── vite.config.ts         # proxies /api to BACKEND_URL (default http://localhost:8000)
│   └── src/
│       ├── api/client.ts      # all backend calls go through here
│       ├── stores/chat.ts     # Pinia: session_id, turns, filters
│       ├── views/HomeView.vue
│       └── components/        # ResultCard.vue, ChatTurn.vue, FilterPanel.vue
├── eval/
│   ├── gold.yaml
│   └── run_eval.py
└── tests/
    ├── test_verify.py
    ├── test_clean.py
    └── test_resolve.py
```

Delete the placeholder `main.py`.

### Dependencies (`uv add ...`)

```
httpx[http2] selectolax psycopg[binary] pgvector sentence-transformers
openai pydantic pydantic-settings pyyaml typer tenacity unidecode rapidfuzz
fastapi==0.144.0 uvicorn==0.54.0
langgraph==1.2.16 langchain-openai==1.7.2          # [PoC] chat agent
```

Dev: `pytest`.

Versions of the new packages are pinned (latest on PyPI on 2026-10-18), because LangChain-family APIs change often.
Frontend: `npm ci` in `frontend/` (versions in `frontend/package.json`).

---

## 6. Infrastructure

### 6.1 `docker-compose.yml` (live file, #31)

Services: `db` (pgvector/pgvector:pg16), `app` (`navigator serve` on port 8000, healthcheck on `/api/stats`, bge-m3 cache in the `hf_cache` volume, `EXTRACT_MODEL` defaults to `apertus-v1-5-8b`) and `frontend` (node:24-slim, Vite dev server on 5173, `BACKEND_URL=http://app:8000`, starts when `app` is healthy). Host ports come from `DB_PORT`, `API_PORT` and `UI_PORT`, so a second stack with its own volumes can run under another project name (`docker compose -p navclean ...`).

### 6.2 `Dockerfile` (live file, #31)

`python:3.12-slim` + uv. Dependencies are installed in their own layer, and the uv download cache is a BuildKit cache mount, so it stays out of the image. `torch` comes from the CPU-only index on Linux (`[tool.uv.sources]` in `pyproject.toml`): the default wheel pulls ~4 GB of CUDA libraries. Image: ~2 GB.

### 6.3 Commands

```bash
docker compose up -d db
docker compose run --rm app uv run navigator init-db
docker compose run --rm app uv run navigator ingest            # init-db + crawl + embed + extract + verify + resolve, all sources
docker compose run --rm app uv run navigator ingest --source dcb
docker compose run --rm app uv run navigator eval
docker compose up app frontend                                 # UI at http://localhost:5173, API at http://localhost:8000/api
```

For fast local development, people MAY also run `uv run navigator ...` on the host with `DATABASE_URL=postgresql://navigator:navigator@localhost:5432/navigator`, and `npm run dev` in `frontend/` (it proxies `/api` to `localhost:8000`).

### 6.4 `.env.example`

```
KEERA_API_KEY=
LLM_BASE_URL=https://gateway.keera.ch/api/v1
LLM_MODEL=apertus-v1-5-70b
LLM_CONCURRENCY=8
EMBED_MODEL=BAAI/bge-m3
DATABASE_URL=postgresql://navigator:navigator@localhost:5432/navigator
JUDGE_ENABLED=true          # [PoC] false skips section 7.8
```

---

## 7. Ingestion pipeline

Run order for each source: crawl → clean → chunk → embed → extract → verify → resolve → judge [PoC].
Each step MUST be safe to re-run (idempotent). Re-ingesting a source deletes that source's old pages, chunks and claims first (cascade), then writes new data. This also covers the data-protection rule "replace on recrawl".

### 7.1 Database schema (`src/navigator/schema.sql`)

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source (
  id          text PRIMARY KEY,           -- 'artorg', 'dcb', 'unibe'
  name        text NOT NULL
);

CREATE TABLE IF NOT EXISTS page (
  id          serial PRIMARY KEY,
  source_id   text NOT NULL REFERENCES source(id) ON DELETE CASCADE,
  url         text NOT NULL UNIQUE,
  title       text,
  text        text NOT NULL,              -- cleaned text; quotes are checked against this
  fetched_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chunk (
  id          serial PRIMARY KEY,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  ord         int NOT NULL,
  text        text NOT NULL,
  embedding   vector(1024),
  tsv         tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX IF NOT EXISTS chunk_tsv_idx ON chunk USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunk_emb_idx ON chunk USING hnsw (embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS entity (
  id          serial PRIMARY KEY,
  type        text NOT NULL CHECK (type IN ('person','unit','project','infrastructure')),
  name        text NOT NULL,              -- display name
  norm_key    text NOT NULL,              -- merge key, see section 7.7
  UNIQUE (type, norm_key)
);

CREATE TABLE IF NOT EXISTS claim (
  id          serial PRIMARY KEY,
  entity_id   int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  field       text NOT NULL,              -- see section 7.5
  value       text NOT NULL,
  quote       text NOT NULL,              -- exact text from page.text
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false,
  judge_verdict text CHECK (judge_verdict IN ('supported','partial','unsupported')),  -- [PoC] NULL = not judged
  judge_reason  text                                                                   -- [PoC]
);
CREATE INDEX IF NOT EXISTS claim_entity_idx ON claim(entity_id);
CREATE INDEX IF NOT EXISTS claim_page_idx ON claim(page_id);

CREATE TABLE IF NOT EXISTS relation (
  id          serial PRIMARY KEY,
  from_id     int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rel         text NOT NULL CHECK (rel IN ('member_of','works_on','part_of','provides','listed_in')),
  to_id       int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  quote       text NOT NULL,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false,
  judge_verdict text CHECK (judge_verdict IN ('supported','partial','unsupported')),  -- [PoC]
  judge_reason  text,                                                                  -- [PoC]
  UNIQUE (from_id, rel, to_id, page_id)
);

-- [PoC] User feedback from the UI. Log only: it never changes what is shown.
-- entity/claim ids change on re-ingest, so keep a text snapshot; ids become NULL.
CREATE TABLE IF NOT EXISTS feedback (
  id          serial PRIMARY KEY,
  session_id  text NOT NULL,
  query       text,
  entity_id   int REFERENCES entity(id) ON DELETE SET NULL,
  claim_id    int REFERENCES claim(id) ON DELETE SET NULL,
  entity_name text,                       -- snapshot
  claim_text  text,                       -- snapshot "field: value — quote"
  rating      text NOT NULL CHECK (rating IN ('up','down','wrong_fact')),
  comment     text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

Entities with no verified claims left after a re-ingest SHOULD be deleted by a cleanup query at the end of `ingest`.

**Raw extraction tables (as built):** `raw_claim` and `raw_relation` store every extracted item with `verified` and `fail_reason`, before merging. `resolve` reads them, so it can be re-run without LLM calls. A re-crawl deletes them with the page (cascade).

**Shown claim** (used everywhere below): `verified = true AND judge_verdict IS DISTINCT FROM 'unsupported'`. Same rule for relations. Without the judge (NULL verdict), this is the same as `verified = true`.

### 7.2 Crawl (`crawl.py`)

- Async `httpx` client. Follow redirects. Timeout from config.
- Respect `robots.txt` per host (`urllib.robotparser`). Wait `delay_seconds` between requests to the same host.
- Breadth-first from seeds, up to `max_depth`.
- Link filter, in this order: host allowed → not denied → matches an `include_patterns` regex → does not match any `exclude_patterns` regex → allowed by robots.txt.
- Normalise URLs: drop `#fragment`, drop trailing whitespace, resolve relative links (`./x`, `//host/x`).
- Queue order: URLs that match `priority_patterns` go first. Seeds always go first.
- Only keep responses with `content-type` `text/html`. Skip PDFs for now.
- Stop when `max_pages` pages are stored for this source.
- Log every fetched URL with HTTP status.

### 7.3 Clean (`clean.py`)

1. Main text: visible text of the main container (`main`, `[role=main]`, `#main-content`, `#main`, `#content`, `article`, else `body`) with `selectolax`, after dropping `script`, `style`, `nav`, `header`, `footer`, `form`, `svg`, `iframe`, `button`. One line per text block. **Do not use trafilatura:** on team pages it dropped almost all names and emails (DCB team page: 597 of 4,243 characters kept).
2. **Decode hidden emails.** In the raw HTML, find `String.fromCharCode(<numbers>)` and decode to characters. Also find plain `mailto:` links. Ignore `mailto:?body=` share links.
3. If the link text is not the email (DCB shows "Mail"), replace the link text with the email **inline**, so the name, role and email stay together in one quotable block. Emails that are not in the main text are appended in a section:
   ```
   Contact emails on this page:
   - <link text or "email">: <email>
   ```
   This makes emails quotable and verifiable.
4. Normalise whitespace: collapse spaces, one visible block per line. The output has almost no blank lines (7 of 100 pages), so later steps split on single line breaks.
5. Title: the `<title>` tag, without the site suffix.

The cleaned text is stored in `page.text`. It is the ground truth for quote checks.

### 7.4 Chunk and embed (`chunk.py`, `embed.py`)

- Split `page.text` on line breaks (the cleaner writes one block per line, see 7.3). Split lines longer than 1,200 characters at word boundaries. Pack the lines into chunks of about 1,200 characters; each chunk starts with the last ~200 characters of the previous one (cut at a word boundary). Prefix every chunk with the page title, like `"<title>\n\n<chunk text>"`, so short chunks keep their context.
- Embed with `SentenceTransformer("BAAI/bge-m3")`, `normalize_embeddings=True`, batch size 16. Store in `chunk.embedding`.
- Load the model once per process (module-level cache). It is also used at query time.
- Store with `chunks_db.replace_chunks` (delete the source's chunks, insert the new ones). Re-crawling a source deletes its pages and, by cascade, its chunks: run `navigator embed --source ID` again after `navigator crawl`.
- Measured: 377 chunks for the 100 pages (artorg 92, dcb 211, unibe 74), embedded in ~20 s.

### 7.5 Extract (`extract.py`, `llm.py`)

> **As built (differs from the text below, learned from live runs):**
> - **Two focused prompts per page part**: `PEOPLE_PROMPT` (people, role/email/phone, `member_of`) and `TOPICS_PROMPT` (units, projects, infrastructure, expertise). One combined prompt often returned only one of the two.
> - The prompts list the **allowed fields per entity type** (without it the model invented `website`, `address`, `organization`) and require **contiguous** quotes. Examples cover a member list and a lab page.
> - **Compact rows** instead of objects: `[entity_type, entity_name, field, value, quote]` and `[from_type, from_name, rel, to_type, to_name, quote]` (~3x fewer tokens). Rows are routed by length (5 = claim, 6 = relation).
> - Page parts of **6,000** characters, answers up to 12,000 tokens.
> - **Salvage:** when an answer is cut off (8B sometimes loops until `max_tokens`), every complete row is recovered from the text and duplicates are removed.
> - The page **title** counts as page text for verification (unit names often only appear there).
> - Full run (8B, 100 pages, ~10 min): 1,488 / 1,705 claims verified (87%), 259 relations verified, facts on 97 pages. Most rejections are real errors: names copied from the prompt example, invented entity names, author abbreviations.

One LLM call per page. If `page.text` is longer than 12,000 characters, split it into parts of 12,000 characters (on paragraph breaks) and call once per part.

Concurrency: `asyncio.Semaphore(LLM_CONCURRENCY)` (default 8). Retry with `tenacity` on HTTP 429 and 5xx: exponential backoff, max 5 tries. Temperature 0.

**Output format: a flat list of claims.** A flat list is easier for the model and easy to check.

Allowed fields per entity type:

| Entity type | Fields |
|---|---|
| person | `name`, `role`, `email`, `phone`, `expertise`, `bio` |
| unit | `name`, `unit_type` (faculty, department, institute, center, lab, group, service), `description`, `expertise` |
| project | `name`, `description`, `expertise` |
| infrastructure | `name`, `description` (equipment, facility, platform, service) |

Allowed relations: `member_of` (person → unit), `part_of` (unit → unit), `works_on` (person or unit → project), `provides` (unit → infrastructure).

`listed_in` (person → unit) is **not extracted**: `resolve` creates it (#23). It means "this person is listed on this unit's member page". Its quote is the person's name on that page, which supports "listed on", not "is a member of". That is why it is a separate relation and not a `member_of` with a weak quote. The unit's name comes from the first line of the parent page (the member page URL without `group_members/` or `team/`), because member page titles do not name the lab. `schema.sql` re-creates `relation_rel_check`, so existing databases accept it after `navigator init-db`.

**System prompt (use as is, tune only if eval fails):**

```
You extract facts from one web page of a research institution.
Return ONLY a JSON object. No other text.

Rules:
- Only extract facts that are written on the page. Do not guess. Do not add knowledge.
- For every claim, "quote" MUST be copied EXACTLY, character by character, from the page text. 
  Keep it short: one sentence or one line, max 300 characters.
- "value" is the fact in short form. For name, role, email, phone: value MUST appear inside the quote.
- "expertise" values are short topic phrases (2-5 words) like "continuous glucose monitoring",
  "surgical robotics", "cardiac imaging". One claim per topic.
- People: only real named people. Not generic contacts like "info@...".
- If the page has no useful facts, return {"claims": [], "relations": []}.

JSON format:
{
  "claims": [
    {"entity_type": "person|unit|project|infrastructure",
     "entity_name": "...",
     "field": "...",
     "value": "...",
     "quote": "..."}
  ],
  "relations": [
    {"from_type": "...", "from_name": "...", "rel": "member_of|part_of|works_on|provides",
     "to_type": "...", "to_name": "...", "quote": "..."}
  ]
}
```

User message: `"Page URL: <url>\nPage title: <title>\n\nPage text:\n<<<\n<text>\n>>>"`.

Parsing:
1. Call with `response_format={"type": "json_object"}`. If the gateway returns an error for this parameter, retry without it, and remember that for the rest of the run.
2. Parse JSON. If it fails, take the substring from the first `{` to the last `}` and parse again. If it still fails, retry the call once. Then log and skip the page.
3. Validate with Pydantic models. Drop claims with unknown `entity_type`, unknown `field` for that type, or empty values.

### 7.6 Verify quotes (`verify.py`) — the core rule

A claim is `verified = true` only if ALL checks pass:

1. **Quote is in the page.** `norm(quote)` is a substring of `norm(page.text)`.
   `norm()` = Unicode NFKC, replace curly quotes and dashes with ASCII, collapse all whitespace to one space, lowercase.
2. **Value is in the quote** for fields `name`, `role`, `email`, `phone`, and for `entity_name` of the claim (name of the person, unit, etc.): `norm(value)` is a substring of `norm(quote)`.
   Exception: for `entity_name`, it is enough if the name appears anywhere in `norm(page.text)` (the name is often in a heading, not in the same sentence).
3. **Fuzzy fallback** for check 1 only: if the exact check fails, accept if a sliding window of the page has `rapidfuzz.fuzz.ratio >= 95` with the quote. Then replace the stored quote with the exact page text from that window. (Add `rapidfuzz` to dependencies.) This handles small whitespace or punctuation differences.

Relations: the same check 1 on their quote, plus both entity names appear in the page text.

Only verified claims and relations are used in search and in the UI. Unverified ones stay in the database for debugging and for the eval report (count them).

4. **Quote rebuild (as built)** for `name`, `role`, `email`, `phone` only: if the model's quote fails (the 8B model often writes "Name\nRole" where the page has "Role\nName"), the quote is built from the page: for `name` the name's own text; otherwise the shortest page span that holds the entity name and the value, if they are at most 200 characters apart. The stored quote is still exact page text. A value far from the name (another person's role) is rejected.

Unit tests MUST cover: exact match, whitespace difference, curly quote, invented quote (rejected), name not in quote (rejected), reordered quote rebuilt, value far from the name (rejected).

### 7.7 Merge duplicates (`resolve.py`)

Run after verify, over all sources.

`norm_name(name)`: remove titles (`Prof.`, `Dr.`, `PD`, `med.`, `phil.`, `nat.`, `sc.`, `PhD`, `MD`, `MSc`, `BSc`, `Dipl.`, `Ing.`), `unidecode`, lowercase, collapse spaces, sort nothing (keep word order).

Rules for **persons**:
1. If the person has a verified email → `norm_key = "email:" + email.lower()`.
2. Else → `norm_key = "name:" + norm_name(name)`, but only merge two persons with the same normalised name if they share at least one `member_of` unit (same unit `norm_key`), or if they come from the same source. Otherwise keep them separate: add a suffix `"#<source_id>"` to the key.
3. When an email person and a name-only person have the same normalised name and share a unit → merge into the email person.

Rules for **units, projects, infrastructure**: `norm_key = norm_name(name)`. Also strip a leading "the ".

**No fuzzy name matching.** A few duplicates are OK. A wrong merge of two different people is NOT OK.

Implementation hint: during extraction, write claims into a staging list keyed by `(entity_type, entity_name, page_id)`. In `resolve`, compute keys, upsert into `entity`, then insert `claim` and `relation` rows with the final `entity_id`.

### 7.8 Judge claims (`judge.py`) — [PoC]

Quote verification (7.6) proves the quote is on the page. It does NOT prove the quote supports the claim. Example: an `expertise: "surgical robotics"` claim with a correct quote about something else. The judge closes this gap.

Runs after `resolve`, on stored rows, so it can be re-run alone (`navigator judge`). Skip it if `JUDGE_ENABLED=false`.

What is judged:
- Only **verified** claims with field `expertise`, `description`, `bio` or `unit_type`, and all **verified relations**.
- Not `name`, `role`, `email`, `phone`: check 2 of 7.6 already requires the value inside the quote.

How:
- **One call per page** with all judged claims and relations of that page, numbered. Same client, concurrency, retries and JSON parsing as 7.5.
- Write `judge_verdict` and `judge_reason` to each row.
- If the call fails, or a claim id is missing in the answer → leave `judge_verdict` NULL. The claim stays shown. **The judge MUST NOT block or fail the pipeline.**
- Effect on display: `unsupported` → hidden (see "shown claim" in 7.1). `partial` → shown with a small "partial" marker and the reason as tooltip. `supported` → shown normally.

**System prompt (draft, tune with the eval):**

```
You check facts extracted from one web page of a research institution.
For each numbered item, decide if the quote supports the stated fact.
Return ONLY a JSON object. No other text.

Verdicts:
- "supported": the quote states the fact, or the fact is a fair short summary of the quote.
- "partial": the quote is related, but the fact is broader, narrower, or adds a detail
  that the quote does not state.
- "unsupported": the quote does not say this, or says it about another person or unit.

Rules:
- Use ONLY the quote and the names given. Do not use your own knowledge.
- If you are unsure between two verdicts, choose the stricter one.
- "reason": one short sentence.

Examples:
[1] person "Anna Muster" — expertise: "surgical robotics"
    quote: "Her group develops robotic systems for minimally invasive surgery."
    → supported
[2] unit "Diabetes Technology Lab" — expertise: "artificial pancreas"
    quote: "The lab works on continuous glucose monitoring."
    → unsupported (glucose monitoring is not an artificial pancreas)
[3] person "Marc Beispiel" — bio: "leads the cardiac imaging group since 2015"
    quote: "Marc Beispiel leads the cardiac imaging group."
    → partial (the year is not in the quote)
[4] relation: person "Anna Muster" works_on project "SNAQ"
    quote: "SNAQ is developed by the DCB innovation team."
    → unsupported (the quote does not name the person)

JSON format:
{"verdicts": [{"id": 1, "verdict": "supported|partial|unsupported", "reason": "..."}]}
```

User message: `"Page URL: <url>\nPage title: <title>\n\nItems:\n[1] <entity_type> \"<entity name>\" — <field>: \"<value>\"\n    quote: \"<quote>\"\n..."`. Relations as in example [4]. The full page text is NOT sent (shorter, cheaper, and the judge must decide from the quote alone).

**Known limit:** the judge is the same model as the extractor, so it tends to agree with itself. Report its verdict counts (section 10.2), and treat it as a filter for obvious errors, not as proof.

Unit tests SHOULD cover: verdict parsing, missing id → NULL, failed call → all NULL, "shown claim" rule.

As built (`judge.py`, `navigator judge [--source]`; `extract` and `ingest` run it after resolve):
- The prompt adds a `listed_in` rule (#23): it only claims that the person appears on that unit's member list, so it is "supported" if the quote is the person's own entry. Result: 245 of 249 `listed_in` relations supported (3 partial, 1 not judged).
- Max 25 items per call (bigger pages are split), 180 s timeout, all calls in parallel. A re-run first resets the judged rows of those pages, so a missing verdict is NULL, not a stale one. `JUDGE_MODEL` (optional) overrides the model.
- First run (2026-10-18, 70B, 96 pages, ~2.4 min): claims 399 supported / 120 partial / **36 unsupported** / 3 not judged; relations 434 / 35 / 31 / 1. It catches real errors, e.g. an external collaborator ("Prof. Sylviane Muller, Strasbourg") made `member_of` a lab, a unit `works_on` itself, and umbrella-unit topics whose quote is only the page title.
- Eval before → after: recall@10 46% → 46%, judged precision@10 59% → 62%, judge gold agreement 80% → 85%, traceability 100%.

---

## 8. Search (`search.py`, `explain.py`)

Input: query text (any language). Output: up to 10 result objects.

### 8.1 Query expansion (Apertus)

Prompt:

```
You help search a database of research experts in Bern, Switzerland.
Give search terms for the user query: synonyms, technical terms, lay terms,
abbreviations, and German translations. Max 8 English and 8 German terms.
Return ONLY JSON: {"en": ["..."], "de": ["..."]}
Query: <query>
```

Cache results in memory (dict) for the session. If the call fails, continue with the original query only.

As built (`expand.py`, `expand_query(llm, query) -> Expansion(en, de)`; pass `expansion.terms` to `search_chunks`):
- Timeout 10 s (the shared gateway can be slow); timeout or any error → empty expansion, not cached.
- Clean-up: strings only, trimmed, no duplicates, not the query itself, max 8 per language. `"term (ABBR)"` is split into `"term"` and `"ABBR"`, so keyword search can match the abbreviation alone.
- `terms` = English first (the semantic query in 8.3 uses the first 4), duplicates across languages removed.
- Measured (70B, 2026-10-18): 1.3–2.1 s per query. Top-10 page overlap between "glucose sensors" and "continuous glucose monitoring" went from 0.83 to 1.00; "Herzklappen" now ranks ARTORG Cardiovascular Engineering first.

### 8.2 Keyword search

```sql
SELECT id FROM chunk,
  (SELECT plainto_tsquery('simple', :word1) || ... || phraseto_tsquery('simple', :term2) AS q) AS query
WHERE tsv @@ q
ORDER BY ts_rank_cd(tsv, q) DESC LIMIT 50;
```

Build the tsquery in SQL (no manual escaping) as an OR (`||`) of:

1. **The words of the original query**, each with `plainto_tsquery('simple', word)`. Tokenise with `to_tsvector('simple', query)` so words match `chunk.tsv`. Drop English and German stopwords: a word is a stopword if `ts_lexize('english_stem', word)` or `ts_lexize('german_stem', word)` returns `{}`. If only stopwords are left, keep them.
2. **The expansion terms** (8.1): `phraseto_tsquery` for multi-word terms, `plainto_tsquery` for single words.

Do NOT send the original query as one phrase or as an AND of its words. The `'simple'` config does not stem, and pages say "valves", "robotics", "sensor" where users type "valve", "robots", "sensors": phrase/AND found 0 chunks for 3 of 4 test queries. With OR, `ts_rank_cd` still ranks chunks with more of the words, closer together, first. Trade-off: a common word like "research" lifts general index pages; expansion terms sharpen this.

### 8.3 Semantic search

Embed the original query with bge-m3 (same normalisation). Also embed `query + ", " + ", ".join(en_terms[:4])`. Run both:

```sql
SELECT id, page_id, 1 - (embedding <=> :vec) AS sim
FROM chunk ORDER BY embedding <=> :vec LIMIT 50;
```

### 8.4 Fuse and group

1. Reciprocal Rank Fusion over the 3 ranked lists (keyword, semantic-original, semantic-expanded): `score(chunk) = Σ 1 / (60 + rank)`.
2. Map chunks to entities: an entity is linked to a chunk if it has a shown claim (7.1) on the same page (`claim.page_id = chunk.page_id`) whose quote appears in that chunk's text. If none of its quotes are in the chunk, link it at half weight (same page only).
3. Entity score = sum of its best 3 chunk scores.
4. Result types: `person` and `unit` by default. Projects and infrastructure appear inside the person/unit card (via relations), and as their own results only if the UI filter asks for them.

### 8.5 Fairness cap

Go down the ranked list. For each result, find its unit (person → `member_of` unit; unit → itself). Allow max 3 results per unit in the top 10. Skip extra ones and move on. Results with no unit are not capped.

### 8.6 "Why it matches" (Apertus)

One call for all top-10 results together (saves time).

Input per result: entity id, name, and its shown claims (7.1) as a numbered list `[claim_id] field: value — "quote"`.

Prompt:

```
For each result, write ONE short sentence that explains why it matches the query.
Use ONLY the facts listed for that result. Do not add facts.
Cite the claim ids you used in square brackets, like [12][15].
Return ONLY JSON: {"<entity_id>": "<sentence>", ...}
Query: <query>
Results:
<...>
```

Check: every cited claim id must belong to that entity. If a sentence cites no valid id or cites a wrong id → replace it with a template: `"Matches on: <first 2 expertise values>"` (or the best matching chunk's first sentence, if there is no expertise claim).

As built (`explain.py`, wired into `/api/search`):
- **One call per result, in parallel**, not one call for all ten. With one call, Apertus answered only the 1–5 results it found strongest (10 of 40 on 4 test queries); asking again for the missing ones reached 34 of 40 but took 5–8 s. One call per result: **40 of 40 in ~2 s**. Calls still running after 15 s are cancelled, and those results keep the template.
- The prompt adds "a sentence without a claim id is thrown away", "a sentence for EVERY result", the bare id as key, and one worked example (Apertus wrote sentences without ids otherwise).
- At most 10 claims per result in the prompt (expertise, description, role, name first; no email/phone). A citation is valid only if it is one of these ids, so every cited claim is on the card's evidence list.
- `EXPLAIN_MODEL` (optional) runs explanations on another model, e.g. 8B while the gateway is slow.
- Known gap: people whose own evidence is only a role or a member-page listing get true but bland sentences ("… is the contact person [9953]"). Their unit's claims are not on their card, so they can't be cited (follow-up issue).

With lab topics (#42, on top of #44): person evidence may include `unit_expertise` rows with `via_unit`. They are the lab's topics, not the person's. The prompt labels them `lab topic (via <unit>)`, ranks them right after own expertise, and has a worked example ("PhD student in the Sensor Lab, which works on …"). The check adds two rules: a sentence citing a lab topic must name that unit, and a sentence that copies rows (`unit_expertise:`, `role:` …) is rejected. Before, Apertus often turned lab topics into personal expertise ("X specializes in …"). After, 12 of 16 people on 3 queries got a sentence that frames the topic as the lab's; the other 4 keep #44's template. Known limit: a sentence that names the unit but still says "X works on <lab topic> at <unit>" passes the check.

### 8.7 No reliable result

If the best semantic similarity across all chunks is below `MIN_SIM` (start at 0.45, tune with the eval set) AND the keyword search returns no hits → return no results and show:
"No reliable source found for this query. Try other words, or the information may not be public."

Also: never show a result with zero shown claims.

### 8.8 Result object

```python
class Evidence(BaseModel):
    claim_id: int               # needed for "wrong fact" feedback
    field: str
    value: str
    quote: str
    url: str
    judge_verdict: str | None   # [PoC] "supported" | "partial" | None
    judge_reason: str | None    # [PoC]

class Result(BaseModel):
    entity_id: int
    type: Literal["person", "unit", "project", "infrastructure"]
    name: str
    role: list[str]
    contact: list[str]          # emails, phones
    affiliations: list[str]     # unit names via member_of / part_of
    expertise: list[str]
    projects: list[str]
    infrastructure: list[str]
    why: str
    score: float
    sources: list[str]          # distinct page URLs of the claims shown
    evidence: list[Evidence]    # one row per claim shown
```

### 8.9 HTTP API (`api.py`, FastAPI)

`navigator serve` starts `uvicorn navigator.api:app` on port 8000 with **one worker**. All routes are under `/api`. Pydantic models from 8.8 are the response types, so FastAPI documents them at `/docs`.

| Route | Request | Response |
|---|---|---|
| `GET /api/search` | `?q=&source=&type=` | `{results: Result[], expansion: {en, de}, no_result: bool}` — stateless, no chat |
| `POST /api/chat` [PoC] | `{session_id, message, filters?}` | `{reply: str, results: Result[], filters: {source, type}, expansion, no_result}` |
| `POST /api/feedback` [PoC] | `{session_id, query, entity_id, claim_id?, rating, comment?}` | `{ok: true}` |
| `GET /api/stats` | — | counts per source (pages, chunks, entities, shown claims) + feedback counts |

Rules:
- `/api/chat` is **not streaming** (one JSON answer). Streaming (SSE) is later.
- `filters` in a chat request is optional: the UI sends it when the user changes a filter in the side panel. The server writes it into the graph state before the agent runs, so UI and state stay in sync.
- `/api/feedback` writes one `feedback` row (with the text snapshot). It never changes results.
- Load the embedding model at startup (FastAPI lifespan), not on the first request.

### 8.10 Chat agent (`agent.py`, LangGraph) — [PoC]

Goal: refine searches in a conversation. The agent **only calls tools**. It never writes facts about people, units or projects. Every answer is the same result cards as `/api/search`.

LLM: `ChatOpenAI(base_url=settings.llm_base_url, api_key=settings.keera_api_key, model=settings.llm_model, temperature=0)` from `langchain-openai`, with `bind_tools(...)`. Tool calling works on the gateway (section 3).

State:

```python
class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    query: str | None              # last search query
    filters: dict                  # {"source": str | None, "type": str | None}
    last_results: list[Result]     # for "#2", "her", "that lab"
    expansion: dict | None
    rounds: int                    # tool rounds in this user turn
```

Tools (plain Python functions, they call `search.py` and SQL):

| Tool | Action |
|---|---|
| `search(query, source?, type?)` | run section 8 search with the merged filters; set `query`, `last_results` |
| `set_filters(source?, type?)` | change `filters` (null removes one), then re-run the last `query` |
| `more_like(result_number)` | take that result's shown `expertise` claims, search with them joined as the query; exclude the entity itself |
| `related(result_number, rel?)` | walk shown `relation` rows of that entity (both directions), return the linked people/units as results |

`result_number` is the 1-based position in `last_results`. Each tool returns a short summary to the model, like `"#1 [entity 42] Anna Muster — surgical robotics, medical imaging"`, so it can resolve "the 2nd one" or "her" in the next turn.

Graph:

```
START → agent ──(tool calls)──▶ tools ──▶ agent      (max 3 tool rounds per user message)
          └──(no tool call)──▶ respond → END
```

- `tools` is a custom node (not the prebuilt `ToolNode`), because tools must read and write `filters` and `last_results` in the state.
- Checkpointer: `MemorySaver()`. `config={"configurable": {"thread_id": session_id}}`. State is lost when the server restarts. That is OK for the PoC.

**System prompt (draft):**

```
You help users find research experts in Bern (ARTORG Center, Diabetes Center Berne,
University of Bern). You work ONLY by calling tools.
- A new topic → search.
- "only DCB", "only people", "all sources again" → set_filters.
- "more like #2", "similar to the second one" → more_like.
- "who works with her?", "which lab is he in?", "what does this unit run?" → related.
- Results are numbered #1, #2, ... in the last tool output. Use these numbers.
Never state facts about people, units or projects yourself.
After the tools, reply with ONE short sentence that says what you did,
for example: "Showing people at DCB for 'glucose sensors'."
If you mention a fact, cite the claim ids in square brackets, like [12].
```

Guardrails:
- **Fallback:** if the model makes no tool call on the first message, or a tool call has bad arguments, or the gateway fails, or 3 rounds are used → run plain `search(message)` with the current filters. The chat is never worse than the search box.
- **Reply check:** the same citation check as 8.6. If the reply cites an id that is not in `last_results`, or names an entity with no citation → replace it with a template: `"Showing <n> results for '<query>'<filters>."`
- `no_result` (8.7) works the same as in search.

---

## 9. UI (`frontend/`, Vue 3 + PrimeVue)

*Pending teammate review: stack and layout below. The card content is fixed (section 1).*

Stack: Vue 3 + Vite + TypeScript, PrimeVue 5 (`@primeuix/themes`), Pinia, vue-router. All backend calls go through `src/api/client.ts` (`/api/...`). Types in `src/api/types.ts` mirror the Pydantic models in 8.8.

**One page** (`HomeView.vue`), chat layout:
- Title: "Bern Research & Expertise Navigator".
- Chat input at the bottom (PrimeVue `InputText` + `Button`). The first message runs a search. Follow-ups refine it (section 8.10).
- Example query buttons: the 9 gold queries (section 10). They send a first message.
- Each **turn** shows: the user message, the assistant `reply` sentence, a "Search terms used" panel (the expansion, to show synonym handling to the jury), and the result cards. Older turns are collapsed (PrimeVue `Panel`, toggleable).
- Side panel: filters — result type (People / Units / Projects / Infrastructure) and source (ARTORG / DCB / UniBE). They show the `filters` from the last chat response. A change sends `filters` with the next chat request (8.9).
- Side panel: counts from `/api/stats`.
- "New search" button: new `session_id`, empty turns.

**Pinia store** `stores/chat.ts`: `session_id = crypto.randomUUID()`, kept in `sessionStorage` (survives reload, not shared across tabs); `turns[]`; `filters`; `loading`.

**Result card** (`ResultCard.vue`, PrimeVue `Card` + `Tag`):
- name (bold), type tag, source tags
- role, affiliations, contact
- expertise as tags
- projects, infrastructure
- "Why it matches" sentence
- links to source pages (clickable)
- "Evidence" accordion: table (`DataTable`) of field / value / quote / link. **[PoC]** `partial` claims show a small "partial" tag with `judge_reason` as tooltip.
- **[PoC] Feedback:** 👍 / 👎 buttons on the card, and a "wrong fact" button on each evidence row (sends `claim_id`). After a click, show "Thanks" and disable the buttons. Nothing else changes.

Empty state: the "No reliable source found" message.
Footer: "All information comes from public pages of the listed institutions. Click a source link to verify. Not an endorsement."

---

## 10. Evaluation (`eval/`)

### 10.1 Gold set (`eval/gold.yaml`)

3 use cases × 3 phrasings = 9 queries. Phrasings: (a) the site's own wording, (b) a lay term, (c) a synonym.

```yaml
use_cases:
  - id: glucose
    queries:
      - "continuous glucose monitoring"
      - "glucose sensors"
      - "biosensing for diabetes"
    expected:               # fill in AFTER the crawl, by a human, from crawled pages only
      - {name: "...", type: person, url: "..."}
  - id: surgery
    queries:
      - "computer-assisted surgery"
      - "surgical robots"
      - "image-guided intervention"
    expected: []
  - id: cardio
    queries:
      - "cardiovascular engineering"
      - "heart valve research"
      - "heart valve prostheses"   # was "implant materials" (#60)
    expected: []
```

Rules:
- Expected entities MUST be chosen by a human, by reading the crawled pages (`SELECT url, title FROM page`). An agent MAY suggest candidates, but a human confirms them.
- Only pick entities that are on crawled pages. With 100 pages, some use cases may have few matches. If a use case has fewer than 2 expected entities after the crawl, either add 2–3 seed URLs for it to `sources.yaml` and re-ingest, or replace the use case with one the crawled data supports. Write down the change.
- 3–7 expected entities per use case (7 since #60: surgery got a lab the owner confirmed).

### 10.2 Metrics (`eval/run_eval.py`, also `navigator eval`)

For each query, run the full search (including expansion, without the explanation call to save time) and compute:

| Metric | Definition | Target |
|---|---|---|
| recall@10 | share of the use case's expected entities in the top 10 (match by normalised name) | ≥ 0.8 average |
| phrasing overlap | for each use case, mean Jaccard of top-10 entity sets between the 3 phrasings | report |
| lay-term recall | recall@10 for phrasings (b) and (c) only | ≥ 0.8 |
| traceability | share of displayed claims with `verified = true` and a source URL | 100% |
| field fill | for person results: share with role, affiliation, expertise, source filled | report |
| source coverage | pages / entities / verified claims per source | all 3 > 0 |
| extraction drop rate | unverified claims / all claims (from DB) | report (shows the quote check works) |
| judge verdicts [PoC] | counts of supported / partial / unsupported / NULL among judged claims (7.8) | report (shows the judge works) |
| judged precision@10 [PoC] | share of top-10 results the eval judge marks relevant (10.3), mean over the 9 queries | report |
| judge gold agreement [PoC] | share of gold `expected` entities found in the top 10 that the eval judge marks relevant | report; if < 0.8, the judge is not reliable — say so |
| feedback [PoC] | counts of up / down / wrong_fact (from DB) | report |

Output: a Markdown table printed to stdout and saved to `eval/report.md`. Put the numbers in the pitch.

As built (`evaluate.py`, `navigator eval`, `eval/run_eval.py`): the PoC rows (judged precision, judge gold agreement) are not implemented yet (10.3); judge verdict and feedback counts are. Name matching: people match when every word of the gold name is in the result name (titles like "Dr.-Ing." are kept by `norm_name`), units on `norm_unit`. Gold candidates were found with SQL over shown claims by topic (not from search results), then confirmed by a human.

Baseline (2026-10-18, 8B extraction, expansion on): **recall@10 14%** (target 80%), traceability 100%, drop rate 13%. Main causes (see the ranking issue): umbrella units ("ARTORG Center", in two spellings) have claims on nearly every page and take top slots; the expected labs and their heads are pushed out (surgery 0%).

Ranking, #59 (2026-10-18): **recall@10 46% → 59%**, lay-term 47% → 54%, unit_topics fill 78% → 92%, traceability 100%. 14 of 15 gold entities are in the DB, so the misses were ranking, not coverage. Two new signals in `rank.py`:
- **Topic match** (`TOPIC_WEIGHT`): an entity's own `expertise` / `description` claims are embedded (bge-m3, cached per process, first search +1 s) and compared with the query; the best match above `TOPIC_MIN` adds to the score (times IDF). Only the first `TOPICS_PER_PAGE` topics per page count: 8B sometimes loops into 30 generic topics ("medical research").
- **Section owner** (`SECTION_WEIGHT`): a lab with a member page owns the pages under its folder (`/research/aihn/…`), as if it were named in them. The extractor often credits a lab page's topics to the umbrella ("ARTORG Center…"), so the lab, and its head through inheritance, never scored. The deepest folder wins.
- `SENIOR_BOOST` 0.1 → 0.3. A bigger inherited share for heads (tried) lowered recall.

Judged precision fell 63% → 48%, but judge gold agreement fell too (90% → 60%, "not reliable"): the judge rejects new gold hits (Odening Lab and CVRC for "heart valve research", Mougiakakou for CGM). Real noise remains: Motor Learning lab and Acoustic Robotics for surgery queries, and umbrella topics shown as a person's lab topics. Still missed: Stefan Weber (not in the DB), Hearing Research Laboratory, Züger and Stettler for 2 of 3 glucose phrasings.

Lab topics, #70, and gold set update, #60 (2026-10-18): `resolve` moves topic claims that the extractor credited to the umbrella ("ARTORG Center …", named only in the page title) on a lab's own pages to that lab (158 claims). The right labs now surface (AI in Health and Nutrition for glucose, Cardiovascular Engineering for cardio), which first lowered recall against the old gold set (59% → 46%) while judged precision rose (48% → 66%). The owner then confirmed three labs as gold entities (Cardiovascular Engineering, AI in Health and Nutrition, Artificial Intelligence in Medical Imaging) and replaced "implant materials" with "heart valve prostheses" (#60). Result: **recall@10 60%, lay-term 61%**, unit_topics fill 97%, traceability 100%, judged precision 60%, judge gold agreement 73%.

### 10.3 Eval judge (`judge.py`) — [PoC]

The gold set only gives recall. The eval judge gives a precision number without more human labels.

- One call per query, with all top-10 results.
- The judge sees only the query and each result's shown evidence (`field: value — "quote"`). No URLs, no scores.
- Binary verdict per result. Temperature 0. Same model as everything else, so it is biased (section 3). This is a PoC metric, not ground truth.
- If the call fails → mark that query "not judged" and leave it out of the mean.

**Prompt (draft):**

```
You judge results of an expert search in the Bern research ecosystem.
For each result, decide if this person or unit is a good match for the query.
Use ONLY the evidence listed. Do not use your own knowledge.
- relevant = true: the evidence shows work on the query topic or a close sub-topic.
- relevant = false: otherwise, or if the evidence is too thin to tell.
Return ONLY JSON: {"<entity_id>": {"relevant": true|false, "reason": "<one short sentence>"}, ...}
Query: <query>
Results:
<entity_id> <name> (<type>)
  - <field>: <value> — "<quote>"
  ...
```

Save every verdict with its reason to `eval/judge_log.jsonl`, so a human can spot-check it later (section 16).

As built (`eval_judge.py`, not `judge.py`, so it does not collide with the claim judge in 7.8): the prompt above plus one line asking for the bare id as the key (Apertus sometimes copies "4 ARTORG Center" as the key; the parser also accepts a leading id). Max 8 evidence rows per result (a big unit has 120+), quotes cut to 200 characters, 90 s timeout per query, calls in parallel. `navigator eval --no-judge` skips it.
With lab topics (#42): the judge sees `lab topic (via <unit>)` rows first (the 8-row cap used to cut them off), and the prompt says a person is relevant if their unit's topics match. Judge gold agreement 85% → 95–100% (3 runs), judged precision@10 63% → 65%. It still rejects people whose lab doesn't match (e.g. Daniel Ahmed, micro/nanorobotics, for "surgical robots").
First run (2026-10-18): **judged precision@10 47%** over 9 queries, judge gold agreement 100% (6 / 6). Results vary between runs because the expansion terms vary, and the result lists change with them.

---

## 11. CLI (`cli.py`, typer)

`pyproject.toml`: `[project.scripts] navigator = "navigator.cli:app"`.

| Command | Action |
|---|---|
| `navigator init-db` | run `schema.sql`, upsert `source` rows from config |
| `navigator ingest [--source ID] [--max-pages N]` | crawl → clean → chunk → embed → extract → verify → resolve → judge |
| `navigator crawl --source ID` | crawl + clean only (for debugging) |
| `navigator embed [--source ID]` | chunk + embed + store (section 7.4); run again after `crawl` |
| `navigator search-chunks "query" [--k N]` | top chunks with page URL and score (debugging, sections 8.2–8.4 step 1) |
| `navigator extract --source ID` | extract + verify + resolve + judge only (pages already stored) |
| `navigator judge [--source ID]` | [PoC] re-run section 7.8 on stored claims |
| `navigator search "query"` | print results as JSON (for debugging) |
| `navigator serve [--host H] [--port P]` | start the API (section 8.9), one worker |
| `navigator eval [--no-judge]` | run section 10.2 (with the eval judge unless `--no-judge`) |
| `navigator stats` | counts per source, incl. judge verdicts and feedback |

---

## 12. Adding a new source (criterion 6) — must be in README

1. Add a block to `config/sources.yaml` (`id`, `name`, `seeds`, `allow_hosts`, patterns, `max_pages`).
2. Run `docker compose run --rm app uv run navigator init-db` (adds the source row).
3. Run `docker compose run --rm app uv run navigator ingest --source <id>`.
4. The new data is searchable right away. No code change.

---

## 13. Work split and timeline (8 hours)

Person A = pipeline. Person B = search, UI, eval.
Integration contract between A and B: the database schema in section 7.1 and the `Result` model in section 8.8. Agree on these in hour 0, then work in parallel.

| Hour | Person A (pipeline) | Person B (search + UI + eval) |
|---|---|---|
| 0–1 | uv deps, Docker, `schema.sql`, `settings.py`, `sources.yaml`, `init-db`. Test gateway rate limit + JSON mode. | `Result` model, Vue result cards on fake data, FastAPI `/api/search` stub returning fake results, `llm.py` shared client (agree with A). |
| 1–2 | `crawl.py` + `clean.py` (email decoding). Run crawl for all 3 sources (100 pages). | `embed.py`, `chunk.py`. Keyword + semantic search on chunks (works as soon as pages exist). |
| 2–3 | `extract.py` + `verify.py` + unit tests. Run extraction. | Query expansion, RRF. Connect UI to real search (chunk-level results first). |
| 3–4 | `resolve.py` + tests. Check extraction quality on 10 pages by hand; fix prompt. | Grouping by entity, fairness cap, result object from DB. |
| 4–5 | Re-ingest all. `stats` command. Cleanup of orphan entities. SHOULD [PoC]: `judge.py` claim judge (7.8) + `navigator judge`. | Gold set (with A: pick expected entities from crawled pages). `run_eval.py`. |
| 5–6 | Fix pipeline issues found by eval (missing pages → add seeds; bad quotes → prompt). | `explain.py` + citation check, "no reliable source" path, evidence accordion. SHOULD [PoC]: eval judge (10.3). |
| 6–7 | Full run in Docker from clean state. Eval numbers. Tune `MIN_SIM`. | SHOULD [PoC]: `agent.py` + `/api/chat` + chat layout; `feedback` table + `/api/feedback` + buttons. |
| 7–8 | **Both:** README (setup, add a source, data-protection note, architecture diagram), pitch slides, demo script. | |

Fallback if behind at hour 5, in this order: (1) drop the chat [PoC] (keep the search box on `/api/search`), (2) drop the claim judge [PoC] (`JUDGE_ENABLED=false`), (3) drop `explain.py` (use the template sentence), (4) drop source/type filters. **Keep the eval judge** (cheap, adds precision@10 to the pitch). Do NOT drop quote verification or the eval.

---

## 14. Definition of done

- [ ] `docker compose up` from a clean checkout (+ `.env`) starts DB and UI.
- [ ] `navigator ingest` stores ~100 pages from all 3 sources.
- [ ] Every claim shown in the UI is verified and links to its source page.
- [ ] The 9 gold queries return results; eval report exists with the numbers from section 10.2.
- [ ] Synonym demo works: "glucose sensors" and "continuous glucose monitoring" return mostly the same people.
- [ ] A query with no match shows the "No reliable source found" message (demo query: "quantum cryptography").
- [ ] README explains setup, adding a source, and data protection.
- [ ] [PoC] Claims judged `unsupported` are not shown; `partial` ones carry a marker. Eval report has the judge rows.
- [ ] [PoC] Chat demo: "glucose sensors" → "only DCB" → "more like #1" → "who works with them?" works in one session.
- [ ] [PoC] A "wrong fact" click writes a `feedback` row and changes nothing on screen.
- [ ] No secrets in git (`git grep -i keera_api_key` shows only `.env.example` and settings code).

---

## 15. Risks and what to do

| Risk | Sign | Action |
|---|---|---|
| Gateway rate limit | HTTP 429 | lower `LLM_CONCURRENCY` to 4 or 2; backoff already in place |
| Apertus copies quotes inexactly | high drop rate (> 40%) | fuzzy fallback (7.6 step 3); shorten max quote length in prompt; show 2 good examples in prompt |
| Apertus returns non-JSON | parse errors | JSON substring fallback; retry once; lower page part size to 6,000 characters |
| bge-m3 slow on CPU | embedding > 10 min | measured ~20 s for 377 chunks on a dev laptop; fine for 100 pages; if needed, switch `EMBED_MODEL` to `intfloat/multilingual-e5-small` (384 dims — change `vector(1024)` to `vector(384)`) |
| Docker image build slow (torch) | build > 10 min | run pipeline on host with `uv run`, only `db` in Docker; fix image later |
| 100 pages miss a use case | gold set has < 2 expected entities | add targeted seed URLs, re-ingest that source |
| Keyword search misses word forms | `'simple'` config has no stemming ("valve" vs "valves") | OR the query words (8.2) instead of a phrase; expansion adds variants; semantic search covers the rest |
| Pages are German only | few English matches | expansion already adds German terms; bge-m3 is multilingual |
| Wrong person merge | two people shown as one | merge rules are strict on purpose; check `resolve` tests |
| [PoC] Judge agrees with itself (same model) | almost 0% `unsupported` | say it in the pitch; spot-check 10 claims by hand if time allows; it is still a filter for obvious errors |
| [PoC] Judge too strict | many good `expertise` claims `unsupported`, recall@10 drops | compare recall@10 with `JUDGE_ENABLED=false`; loosen the "partial" rule in the prompt; or hide nothing and only mark |
| [PoC] Tool-call drift | agent calls the wrong tool, bad `result_number`, or loops | 3-round cap + fallback to plain search (8.10); add 2 examples to the system prompt |
| [PoC] Chat state lost | server restart or more than one worker | expected for the PoC (`MemorySaver`); run one worker; later `PostgresSaver` |
| [PoC] Frontend/backend contract drift | UI breaks on new fields | `src/api/types.ts` mirrors 8.8; check `/docs` (FastAPI OpenAPI) |

---

## 16. Open items

- Gateway rate limit and JSON-mode support: test in hour 1 (Person A).
- Organisers may provide a UniBE subdomain inventory later. If it appears: add a loader that turns the list into `unibe` seeds, filtered to medicine / life-science hosts. Config change only.
- Organisers' rule on a separate embedding model: we assume a local open model (bge-m3) next to Apertus is allowed. Confirm with organisers if possible.
- [PoC] Frontend stack and chat layout (sections 3, 6.1, 9): confirm with the teammate who made the Vue scaffold.
- [PoC] Judge calibration (after the hackathon): label ~30 claims by hand (supported / partial / unsupported, all 3 verdicts present), include the "wrong fact" feedback rows and spot-checks from `eval/judge_log.jsonl`, and report how often the judge agrees with the labels. Until then, the judge numbers are indicative only.
- [PoC] Later: `PostgresSaver` for chat state, streaming chat (SSE), reranker.
