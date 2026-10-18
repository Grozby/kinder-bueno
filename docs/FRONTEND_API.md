# Frontend ↔ backend API

The Vue frontend (`frontend/`) calls JSON endpoints under `/api`. Types are in
`frontend/src/api/types.ts` — that file is the source of truth on the frontend side.

- **From `PLAN.md` section 8.9 (used as specified):** `POST /api/chat`, `POST /api/feedback`.
  The frontend uses the `Result` / `Evidence` models from section 8.8 everywhere a person, unit,
  project or infrastructure is shown.
- **Added by the frontend (not in the plan yet):** the case endpoints (PDF upload, scoring,
  references, pitch) and the source endpoints below.

Until the backend serves them, the frontend uses an in-memory mock (`frontend/src/api/mock.ts`).
Start the frontend with `VITE_USE_MOCK=false` to call the real backend. In dev, Vite proxies
`/api` to `BACKEND_URL` (default `http://localhost:8000`).

## Flow

1. A user uploads a company's business model PDF → a **case** card in the "New" column.
2. The backend scores how well Canton Bern fits (0–100, with a breakdown) and proposes the top 25
   references (`Result[]`, best first). The UI preselects the first 10.
3. The user **refines** the references with the chat (`/api/chat`, one `session_id` per case:
   `case-<case id>`). Chat results can be added to the case; added ones are selected.
4. The user moves the card to "In review", then "Accepted" — or rejects it.
5. For an accepted case, the user generates a **sales pitch** from the selected references.

## Cases

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/cases` | – | `Case[]` |
| GET | `/api/cases/{id}` | – | `Case` |
| POST | `/api/cases` | `multipart/form-data`, field `file` (PDF) | `Case` with `analysis_status: "pending"` |
| PATCH | `/api/cases/{id}` | `{"status": "new" \| "in_review" \| "accepted" \| "rejected"}` | `Case` |
| GET | `/api/cases/{id}/references?limit=25` | – | `Result[]` (section 8.8), best first |
| POST | `/api/cases/{id}/pitch` | `{"entity_ids": [1, 2, …]}` | `{text, entity_ids, generated_at}` |
| GET | `/api/cases/{id}/pitch` | – | the last pitch, `404` if none yet |

- Upload returns at once. The analysis runs in the background; the frontend polls
  `GET /api/cases/{id}` every 1.5 s until `analysis_status` is `done` or `failed`.
- `score` and each `score_breakdown[].score` are 0–100. `summary` is a short text for the user.
- `entity_ids` can include entities added from the chat, not only the top 25.
  The pitch MUST only use facts from these entities (traceability rule, section 1).
- Upload errors: `413` above 10 MB; `422` if the file is not a PDF, cannot be read, or has no text
  (a scanned PDF). Only the PDF's text is stored, never the file.
- Analysis (#53, ~30–60 s): Apertus reads the text (company name, industry, summary, 3–6 needs), each need
  is searched, and the top 25 references are stored. Until then, and if it fails, `company_name` is
  taken from the file name (`glucora-business-model.pdf` → "Glucora Business Model").
- Score: five fixed criteria, each counting only references whose shown topic claims match a need.
  `rationale` names those matches. `score` is the weighted mean:
  - Research fit (40%): the share of needs covered.
  - Expert pool (20%): 20 per person in a matching lab.
  - Research units (15%): 34 per unit.
  - Infrastructure & labs (15%): 50 per entry.
  - Running projects (10%): 50 per project.

  Each criterion is capped at 100. It measures fit within our sources, not all of Canton Bern.
- References: `why` starts with the need the reference matched (`Matches 'continuous glucose monitoring': …`),
  then a sentence whose claim citations are checked again on every request. `[]` before the analysis
  is done.
- Pitch (#54): plain text, paragraphs separated by a blank line. Every sentence about a reference cites
  claim ids like `[9606]`, all from the selected entities' evidence; sentences that fail the check are
  removed. If none is left, or the gateway fails or takes over 30 s, the text is a template that lists the
  references and their cited topics. Takes ~10–15 s. `404` for an unknown case or entity id, `422` for an
  empty list. The last pitch is stored on the case; the drawer loads it with `GET` when it opens.

## Chat and feedback (section 8.9)

- `POST /api/chat` with `{session_id, message, filters?}`; the frontend reads `reply`, `results`, `no_result`.
  - Served since #50 as a plain chat, without the LangGraph agent of plan 8.10: each message is a new
    search through the same pipeline as `GET /api/search`. "More like #2" or "who works with her?" are
    searched as plain text.
  - `filters` replaces the session's filters; without it, the session keeps the last ones. A blank
    `message` with `filters` re-runs the last query (`422` if the session has none yet).
  - `reply` is a template: `"Showing <n> results for '<query>' (source: dcb, type: person)."`.
    The response also has `filters` (the ones the server used) and `expansion`.
  - Sessions live in the API's memory: they are lost when the API restarts.
- `POST /api/feedback` with `{session_id, query, entity_id, claim_id?, rating, comment?}`.
  `query` is the company name.
  - `rating` is `"up"` or `"down"` for the 👍/👎 buttons on a reference.
  - `rating: "wrong_fact"` with a `claim_id` flags one evidence row (plan 9, "wrong fact" button).
    The UI does not have this button yet.
  - `404` if the entity does not exist or `claim_id` belongs to another entity.
- Chat filters are single values (`ChatFilters`: `source` and `type`, each one value or `null`).
  `GET /api/search` (debugging and eval, not used by the UI) takes several:
  `?q=…&type=person&type=unit&source=dcb`.
- `Evidence.judge_verdict` is `"supported"`, `"partial"` or `null` (not judged). Claims the judge
  marks unsupported are never returned.

## Sources

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/sources` | – | `Source[]` |
| GET | `/api/sources/{id}` | – | `Source` |
| POST | `/api/sources` | `NewSource` | `Source` with `status: "crawling"` |

`NewSource`:

```json
{ "url": "https://…", "name": "optional", "max_depth": 2, "max_pages": 50, "follow_outbound": false }
```

- `follow_outbound: true` means the crawler may also follow links to other hosts.
- While `status` is `crawling`, the frontend polls `GET /api/sources/{id}` every second and draws
  `discovered` (`{url, parent, depth, status}`) as a live graph. A sample of up to ~60 pages is enough.
- `pages`, `entities`, `verified_claims` map to the counts from `navigator stats` / `GET /api/stats`.
- Served since #51 (read-only): `status` is always `"ready"`; `validated` means the source is in
  `config/sources.yaml`, and `root_url` is its first seed. `discovered` is up to 60 stored pages with
  `parent: null`, `depth: 0`, `status: "crawled"`: the crawler does not record the tree yet (#55).
