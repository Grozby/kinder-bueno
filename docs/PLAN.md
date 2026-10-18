# Research & Expertise Navigator — Build Plan

Hackathon: HackApertus — challenge from the Bern Economic Development Agency.
Time budget: 8 hours. Team: 2 people.
This plan is the single source of truth. An agent or a person must be able to build the prototype from this file only.

Writing rules for this file: short sentences, simple words. "MUST" means required. "SHOULD" means do it if time allows.

---

## 1. Goal

Build an end-to-end prototype:

```
public web pages → crawl → clean text → extract facts (with quotes) → verify quotes
→ store in Postgres → search (keyword + semantic) → structured, source-backed results in a web UI
```

A user types a question like "glucose sensors". The system returns people and research units. Each result shows:

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
- User accounts, login, admin UI.
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

- **Traceability:** quote verification (section 7.4). Explanations only use stored quotes (section 8.6).
- **Fair representation:** max 3 results per unit in the top 10 (section 8.5). No ranking boost for big institutes.
- **Accuracy:** if no good match, the UI says "No reliable source found for this query" (section 8.7).
- **Data protection (nDSG / GDPR):** only public fields, every field linked to source, no data from other places, data is replaced on every recrawl. Add a short note in the README.

---

## 3. Fixed decisions

| Topic | Decision |
|---|---|
| Language | Python 3.12, managed with `uv` (project already exists) |
| Run environment | `docker-compose`: one `db` service, one `app` service. No connection to Canton Bern networks. |
| Database | Postgres 16 with `pgvector` (Docker image `pgvector/pgvector:pg16`) |
| LLM | Apertus v1.5 70B via the Keera gateway (OpenAI-compatible API) |
| LLM model name | `apertus-v1-5-70b` for all steps. Do NOT use the `-thinking` variants (slower, extra reasoning text breaks JSON parsing). |
| Embeddings | `BAAI/bge-m3` (1024 dimensions, multilingual), runs locally on CPU via `sentence-transformers`. The gateway has no embedding model. |
| Keyword search | Postgres full-text search, `simple` config (mixed German/English text) |
| UI | Streamlit |
| Crawl size | **100 pages total** to start. Configurable. Scale up later. |
| Graph DB | Not now. Postgres tables `entity` + `relation` keep the data graph-shaped. |
| Reranker | SHOULD only: `BAAI/bge-reranker-v2-m3` on top 50, only if time remains at hour 6. |

### LLM endpoint facts (checked)

- Base URL: `https://gateway.keera.ch/api/v1`
- Auth: header `Authorization: Bearer $KEERA_API_KEY`
- Available models: `apertus-v1-5-70b`, `apertus-v1-5-70b-thinking`, `apertus-v1-5-8b`, `apertus-v1-5-8b-thinking`
- Test call to `apertus-v1-5-70b`: works, ~1.3 s for a short answer.
- Rate limits: **unknown**. Check in hour 1 (send 16 parallel requests, look for HTTP 429).
- JSON mode (`response_format={"type": "json_object"}`): **unknown**. Try it. If the gateway rejects it, remove it and parse the first JSON object from the text.

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
│   ├── search.py              # expansion, hybrid search, RRF, grouping, fairness
│   ├── explain.py             # "why it matches" sentences
│   └── cli.py                 # typer CLI
├── app/
│   └── streamlit_app.py
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
openai pydantic pydantic-settings pyyaml typer streamlit tenacity unidecode rapidfuzz
```

Dev: `pytest`.

---

## 6. Infrastructure

### 6.1 `docker-compose.yml`

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: navigator
      POSTGRES_PASSWORD: navigator
      POSTGRES_DB: navigator
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U navigator"]
      interval: 5s
      retries: 10

  app:
    build: .
    env_file: .env
    environment:
      DATABASE_URL: postgresql://navigator:navigator@db:5432/navigator
      HF_HOME: /cache/hf
    depends_on:
      db: { condition: service_healthy }
    ports: ["8501:8501"]
    volumes:
      - hf_cache:/cache/hf          # keeps the bge-m3 download (~2.3 GB) between runs
      - ./config:/app/config
      - ./eval:/app/eval
    command: uv run streamlit run app/streamlit_app.py --server.address 0.0.0.0

volumes:
  pgdata:
  hf_cache:
```

### 6.2 `Dockerfile`

```dockerfile
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN uv sync --frozen --no-dev
```

Note: torch (pulled in by sentence-transformers) is large. To keep the image small, install the CPU-only torch wheel (`--index-url https://download.pytorch.org/whl/cpu`) via a `[tool.uv.sources]` entry. If this costs more than 15 minutes, skip it and accept the big image.

### 6.3 Commands

```bash
docker compose up -d db
docker compose run --rm app uv run navigator init-db
docker compose run --rm app uv run navigator ingest            # crawl + clean + chunk + embed + extract + verify + resolve, all sources
docker compose run --rm app uv run navigator ingest --source dcb
docker compose run --rm app uv run navigator eval
docker compose up app                                          # UI at http://localhost:8501
```

For fast local development, people MAY also run `uv run navigator ...` on the host with `DATABASE_URL=postgresql://navigator:navigator@localhost:5432/navigator`.

### 6.4 `.env.example`

```
KEERA_API_KEY=
LLM_BASE_URL=https://gateway.keera.ch/api/v1
LLM_MODEL=apertus-v1-5-70b
LLM_CONCURRENCY=8
EMBED_MODEL=BAAI/bge-m3
DATABASE_URL=postgresql://navigator:navigator@localhost:5432/navigator
```

---

## 7. Ingestion pipeline

Run order for each source: crawl → clean → chunk → embed → extract → verify → resolve.
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
  verified    boolean NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS claim_entity_idx ON claim(entity_id);
CREATE INDEX IF NOT EXISTS claim_page_idx ON claim(page_id);

CREATE TABLE IF NOT EXISTS relation (
  id          serial PRIMARY KEY,
  from_id     int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  rel         text NOT NULL CHECK (rel IN ('member_of','works_on','part_of','provides')),
  to_id       int NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
  quote       text NOT NULL,
  page_id     int NOT NULL REFERENCES page(id) ON DELETE CASCADE,
  verified    boolean NOT NULL DEFAULT false,
  UNIQUE (from_id, rel, to_id, page_id)
);
```

Entities with no verified claims left after a re-ingest SHOULD be deleted by a cleanup query at the end of `ingest`.

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
4. Normalise whitespace (collapse spaces, keep paragraph breaks).
5. Title: the `<title>` tag, without the site suffix.

The cleaned text is stored in `page.text`. It is the ground truth for quote checks.

### 7.4 Chunk and embed (`chunk.py`, `embed.py`)

- Split `page.text` on paragraph breaks. Pack paragraphs into chunks of about 1,200 characters, with 200 characters of overlap. Prefix every chunk with the page title, like `"<title>\n\n<chunk text>"`, so short chunks keep their context.
- Embed with `SentenceTransformer("BAAI/bge-m3")`, `normalize_embeddings=True`, batch size 16. Store in `chunk.embedding`.
- Load the model once per process (module-level cache). It is also used at query time.

### 7.5 Extract (`extract.py`, `llm.py`)

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

Unit tests MUST cover: exact match, whitespace difference, curly quote, invented quote (rejected), name not in quote (rejected).

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

### 8.2 Keyword search

```sql
SELECT id, page_id, ts_rank_cd(tsv, q) AS score
FROM chunk, to_tsquery('simple', :tsquery) q
WHERE tsv @@ q
ORDER BY score DESC LIMIT 50;
```

Build `:tsquery` as an OR of all terms (original + expansions). Multi-word terms become phrase queries with `<->`. Escape special characters. Simplest safe way: for each term, call `plainto_tsquery('simple', term)` (or `phraseto_tsquery` for multi-word terms) in SQL and combine with `||`.

### 8.3 Semantic search

Embed the original query with bge-m3 (same normalisation). Also embed `query + ", " + ", ".join(en_terms[:4])`. Run both:

```sql
SELECT id, page_id, 1 - (embedding <=> :vec) AS sim
FROM chunk ORDER BY embedding <=> :vec LIMIT 50;
```

### 8.4 Fuse and group

1. Reciprocal Rank Fusion over the 3 ranked lists (keyword, semantic-original, semantic-expanded): `score(chunk) = Σ 1 / (60 + rank)`.
2. Map chunks to entities: an entity is linked to a chunk if it has a verified claim on the same page (`claim.page_id = chunk.page_id`) whose quote appears in that chunk's text. If none of its quotes are in the chunk, link it at half weight (same page only).
3. Entity score = sum of its best 3 chunk scores.
4. Result types: `person` and `unit` by default. Projects and infrastructure appear inside the person/unit card (via relations), and as their own results only if the UI filter asks for them.

### 8.5 Fairness cap

Go down the ranked list. For each result, find its unit (person → `member_of` unit; unit → itself). Allow max 3 results per unit in the top 10. Skip extra ones and move on. Results with no unit are not capped.

### 8.6 "Why it matches" (Apertus)

One call for all top-10 results together (saves time).

Input per result: entity id, name, and its verified claims as a numbered list `[claim_id] field: value — "quote"`.

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

### 8.7 No reliable result

If the best semantic similarity across all chunks is below `MIN_SIM` (start at 0.45, tune with the eval set) AND the keyword search returns no hits → return no results and show:
"No reliable source found for this query. Try other words, or the information may not be public."

Also: never show a result with zero verified claims.

### 8.8 Result object

```python
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
    evidence: list[Evidence]    # (field, value, quote, url) for each claim shown
```

---

## 9. UI (`app/streamlit_app.py`)

- Title: "Bern Research & Expertise Navigator".
- One search box. Example query buttons: the 9 gold queries (section 10).
- Filter: result type (People / Units / Projects / Infrastructure), source (ARTORG / DCB / UniBE).
- Expander "Search terms used": shows the query expansion (shows the synonym handling to the jury).
- One card per result:
  - name (bold), type badge, source badges
  - role, affiliations, contact
  - expertise as tags
  - projects, infrastructure
  - "Why it matches" sentence
  - links to source pages (clickable)
  - expander "Evidence": table of field / value / quote / link
- Empty state: the "No reliable source found" message.
- Footer: "All information comes from public pages of the listed institutions. Click a source link to verify. Not an endorsement."
- Sidebar: counts of pages, chunks, entities, verified claims per source.

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
      - "implant materials"
    expected: []
```

Rules:
- Expected entities MUST be chosen by a human, by reading the crawled pages (`SELECT url, title FROM page`). An agent MAY suggest candidates, but a human confirms them.
- Only pick entities that are on crawled pages. With 100 pages, some use cases may have few matches. If a use case has fewer than 2 expected entities after the crawl, either add 2–3 seed URLs for it to `sources.yaml` and re-ingest, or replace the use case with one the crawled data supports. Write down the change.
- 3–6 expected entities per use case.

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

Output: a Markdown table printed to stdout and saved to `eval/report.md`. Put the numbers in the pitch.

---

## 11. CLI (`cli.py`, typer)

`pyproject.toml`: `[project.scripts] navigator = "navigator.cli:app"`.

| Command | Action |
|---|---|
| `navigator init-db` | run `schema.sql`, upsert `source` rows from config |
| `navigator ingest [--source ID] [--max-pages N]` | crawl → clean → chunk → embed → extract → verify → resolve |
| `navigator crawl --source ID` | crawl + clean only (for debugging) |
| `navigator extract --source ID` | extract + verify + resolve only (pages already stored) |
| `navigator search "query"` | print results as JSON (for debugging) |
| `navigator eval` | run section 10.2 |
| `navigator stats` | counts per source |

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
| 0–1 | uv deps, Docker, `schema.sql`, `settings.py`, `sources.yaml`, `init-db`. Test gateway rate limit + JSON mode. | `Result` model, Streamlit cards on fake data, `llm.py` shared client (agree with A). |
| 1–2 | `crawl.py` + `clean.py` (email decoding). Run crawl for all 3 sources (100 pages). | `embed.py`, `chunk.py`. Keyword + semantic search on chunks (works as soon as pages exist). |
| 2–3 | `extract.py` + `verify.py` + unit tests. Run extraction. | Query expansion, RRF. Connect UI to real search (chunk-level results first). |
| 3–4 | `resolve.py` + tests. Check extraction quality on 10 pages by hand; fix prompt. | Grouping by entity, fairness cap, result object from DB. |
| 4–5 | Re-ingest all. `stats` command. Cleanup of orphan entities. | Gold set (with A: pick expected entities from crawled pages). `run_eval.py`. |
| 5–6 | Fix pipeline issues found by eval (missing pages → add seeds; bad quotes → prompt). | `explain.py` + citation check, "no reliable source" path, evidence expander. |
| 6–7 | **Both:** full run in Docker from clean state. Eval numbers. SHOULD: reranker. Tune `MIN_SIM`. | |
| 7–8 | **Both:** README (setup, add a source, data-protection note, architecture diagram), pitch slides, demo script. | |

Fallback if behind at hour 5: drop `explain.py` (use the template sentence), drop the reranker, drop source/type filters. Do NOT drop quote verification or the eval.

---

## 14. Definition of done

- [ ] `docker compose up` from a clean checkout (+ `.env`) starts DB and UI.
- [ ] `navigator ingest` stores ~100 pages from all 3 sources.
- [ ] Every claim shown in the UI is verified and links to its source page.
- [ ] The 9 gold queries return results; eval report exists with the numbers from section 10.2.
- [ ] Synonym demo works: "glucose sensors" and "continuous glucose monitoring" return mostly the same people.
- [ ] A query with no match shows the "No reliable source found" message (demo query: "quantum cryptography").
- [ ] README explains setup, adding a source, and data protection.
- [ ] No secrets in git (`git grep -i keera_api_key` shows only `.env.example` and settings code).

---

## 15. Risks and what to do

| Risk | Sign | Action |
|---|---|---|
| Gateway rate limit | HTTP 429 | lower `LLM_CONCURRENCY` to 4 or 2; backoff already in place |
| Apertus copies quotes inexactly | high drop rate (> 40%) | fuzzy fallback (7.6 step 3); shorten max quote length in prompt; show 2 good examples in prompt |
| Apertus returns non-JSON | parse errors | JSON substring fallback; retry once; lower page part size to 6,000 characters |
| bge-m3 slow on CPU | embedding > 10 min | fine for 100 pages; if needed, switch `EMBED_MODEL` to `intfloat/multilingual-e5-small` (384 dims — change `vector(1024)` to `vector(384)`) |
| Docker image build slow (torch) | build > 10 min | run pipeline on host with `uv run`, only `db` in Docker; fix image later |
| 100 pages miss a use case | gold set has < 2 expected entities | add targeted seed URLs, re-ingest that source |
| Pages are German only | few English matches | expansion already adds German terms; bge-m3 is multilingual |
| Wrong person merge | two people shown as one | merge rules are strict on purpose; check `resolve` tests |

---

## 16. Open items

- Gateway rate limit and JSON-mode support: test in hour 1 (Person A).
- Organisers may provide a UniBE subdomain inventory later. If it appears: add a loader that turns the list into `unibe` seeds, filtered to medicine / life-science hosts. Config change only.
- Organisers' rule on a separate embedding model: we assume a local open model (bge-m3) next to Apertus is allowed. Confirm with organisers if possible.
