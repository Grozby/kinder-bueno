# Frontend ↔ backend API

The Vue frontend (`frontend/`) calls JSON endpoints under `/api`. Types are in
`frontend/src/api/types.ts` — that file is the source of truth on the frontend side.

- **From `PLAN.md` section 8.9 (used as specified):** `POST /api/chat`, `POST /api/feedback`.
  The frontend uses the `Result` / `Evidence` models from section 8.8 everywhere a person, unit,
  project or infrastructure is shown.
- **The case board (`PLAN.md` section 9.1):** the case endpoints (PDF upload, scoring, references,
  pitch, drawer state) and the source and page endpoints below.

The UI talks to the real backend. `VITE_USE_MOCK=true` swaps in an in-memory mock
(`frontend/src/api/mock.ts`) for UI work on routes the backend does not serve yet;
`VITE_SHOW_UNFINISHED=true` shows controls whose backend is not there yet (the chat examples, #97). In dev, Vite proxies
`/api` to `BACKEND_URL` (default `http://localhost:8000`); in the Docker image, nginx does
(`frontend/deploy/default.conf.template`) and adds `API_TOKEN`.

## Flow

1. A user uploads a company's business model PDF → a **case** card in the "New" column.
2. The backend scores how well Canton Bern fits (0–100, with a breakdown) and proposes the top 25
   references (`Result[]`, best first). The first 10 that match a need are preselected.
3. The user **refines** the references with the chat (`/api/chat`, one `session_id` per case:
   `case-<case id>`). Chat results can be added to the case; added ones are selected.
4. The user moves the card to "In review", then "Accepted" — or rejects it.
5. For an accepted case, the user generates a **sales pitch** from the selected references, and a **partner
   report** (.docx) and **slides** (.pptx) for the research partners.

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
| POST | `/api/cases/{id}/documents` | – | `CaseDocuments` with `status: "pending"` |
| GET | `/api/cases/{id}/documents` | – | `CaseDocuments`: `{status, entity_ids, started_at, generated_at, error}` |
| GET | `/api/cases/{id}/documents/report` | – | the report, `.docx` (attachment) |
| GET | `/api/cases/{id}/documents/slides` | – | the slides, `.pptx` (attachment) |
| POST | `/api/cases/{id}/references` | `{"entity_id": n}` | `Result` with `added: true` |
| DELETE | `/api/cases/{id}/references/{entity_id}` | – | `{entity_ids}`, the selection |
| GET | `/api/cases/{id}/selection` | – | `{entity_ids}` |
| PUT | `/api/cases/{id}/selection` | `{"entity_ids": [1, 2, …]}` | `{entity_ids}` |
| GET | `/api/cases/{id}/chat` | – | `[{message, response: ChatResponse, created_at}]`, oldest first |
| GET | `/api/cases/{id}/feedback` | – | `{ratings: {entity_id: "up" \| "down"}, flagged: [claim_id, …]}` |

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
- References: `why` starts with the need: `Matches 'continuous glucose monitoring': …` when a claim matched it
  (it counts in the score), `Found for '…'` when the search found the reference but no claim matched,
  then a sentence whose claim citations are checked again on every request. `[]` before the analysis
  is done, and when no reference matches any need (a 0-fit case, #110): only chat-added ones are listed then.
  Order (#123): the `Matches` references first, then the `Found for` ones, each in the search's order;
  chat-added ones last.
- Pitch (#54): plain text, paragraphs separated by a blank line. Every sentence about a reference cites
  claim ids like `[9606]`, all from the selected entities' evidence; sentences that fail the check are
  removed. If none is left, or the gateway fails or takes over 30 s, the text is a template that lists the
  references and their cited topics. Takes ~10–15 s. `404` for an unknown case or entity id, `422` for an
  empty list. The last pitch is stored on the case; the drawer loads it with `GET` when it opens.
- Citations in the UI (#109, frontend only; `utils/citations.ts`). A run of ids (`[12][15]`, `[12] [15]` or
  `[12, 15]`, the forms `explain.cited_ids` accepts) is one group.
  - In the pitch and in chat results, each group shows as a small number. A click opens the cited facts,
    with value, quote and source link, taken from the evidence rows of the references in the drawer.
  - A group with an id outside that evidence stays as written, so a citation is never hidden.
  - A reference row's one-line `why` shows no ids: they would sit past the ellipsis, and the row's evidence
    button lists the same facts.
  - "Copy" on the pitch writes each group as numbers of its source pages (`[1]`, one per distinct page) and
    adds a `Sources:` list with the URLs, like the partner report.
- Report and slides (#96): made from the stored selection, in the background (~1 min); poll
  `GET …/documents` until `status` is `done` or `failed` (`none` before the first run).
  - `POST` needs an accepted case (`409` otherwise) and a non-empty selection (`422`). While a job runs, it returns
    that job instead of starting another. A job pending for over 15 min shows as `failed` (the API restarted).
  - Report: summary, the company, the Canton Bern fit (score and breakdown), one section per partner (role,
    unit, contact, why it matches, a profile, up to 6 evidence rows with quotes) and the sources: every page with
    its institution, title, crawl date and link. The summary and the profiles are written by Apertus and checked
    like the pitch; citations become numbers of the sources list (`[3]`). About 10 pages with 10 partners.
  - Slides, for the research partners: title, the company, its needs, the partners matched, one slide per
    partner (topics, matched need, contact, source URLs; quotes and URLs in the speaker notes), next steps
    and sources. Bullets are stored claim values, no LLM text.
  - The files are stored as generated. Download links work through the Vite proxy like every `/api` call.
- Drawer state (#81): the backend keeps it, so a reload or a teammate sees the same.
  - Selection: the references chosen for the pitch. Until the first `PUT` it is the first 10 references
    that match a need ("Found for" ones are not preselected, #110); `[]` is a valid selection. Entities gone since a re-ingest are left out. `404` for unknown entity ids.
  - References added from the chat: `GET …/references` returns them after the top 25, with `added: true`.
    `why` is the sentence of the entity's last chat result in the case's session, checked again on every
    request like the others. `DELETE` removes an added reference and deselects it (`404` if it was not added).
  - Chat: the turns of the session `case-<id>` are stored by `POST /api/chat`; their results are rebuilt from
    the current claims when read. After an API restart, the session's last query and filters are restored
    from them, so a blank message with `filters` still works.
  - Feedback: the last 👍/👎 per entity and the claims flagged in the session `case-<id>`.

## Review, notes and similar cases

The reviewer can give a case their own score and write notes; the card links to earlier cases that
look alike. Served since #108. `Case` has three more fields (the UI treats a missing field as empty):

| Field | Type | Meaning |
|---|---|---|
| `review` | `Review \| null` | `{score 0–100, reason, author, reviewed_at}`: the reviewer's score, next to the AI `score`, never replacing it |
| `notes_count` | `int` | number of notes, for the card |
| `similar_cases` | `SimilarCase[]` | up to 3 earlier cases, best first |

| Method | Path | Body | Returns |
|---|---|---|---|
| PUT | `/api/cases/{id}/review` | `{score, reason, author}` | `Case` |
| DELETE | `/api/cases/{id}/review` | – | `Case` (`review: null`) |
| GET | `/api/cases/{id}/notes` | – | `CaseNote[]` (`{id, author, text, created_at}`), oldest first |
| POST | `/api/cases/{id}/notes` | `{author, text}` | `CaseNote` |
| DELETE | `/api/cases/{id}/notes/{note_id}` | – | `{ok: true}` |

- `reason` is required: `422` when empty. `score` is clamped to 0–100.
- No user accounts (PLAN non-goals): `author` is a name the reviewer types once; the browser keeps it.
- Notes are internal. They MUST NOT go into the pitch or any LLM prompt that writes public text.

**`SimilarCase`**: `{case_id, company_name, status, score, review, similarity 0–1, duplicate,
shared_needs: string[], shared_references: int}`. Only cases uploaded **before** this one (the ones
"already worked on"), any status, rejected included. Computed when the case is read, so `status` and
`review` are current:

- `similarity`: cosine of the bge-m3 embeddings of `summary` + `needs`, stored by the analysis; kept
  when ≥ 0.6. Cases analysed before #108 have no embedding: they only show up as duplicates (`0`).
- `duplicate`: same company name (lowercased, without punctuation and legal form: AG, GmbH, SA, …) or
  the same PDF text; listed first.
- `shared_needs`: needs both cases have (same text, ignoring case and spaces); `shared_references`:
  entity ids both cases have in their top 25 `refs`. These explain the match in the UI.

## Chat and feedback (section 8.9)

- `POST /api/chat` with `{session_id, message, filters?}`; the frontend reads `reply`, `results`, `no_result`.
  - Served since #50 as a plain chat, without the LangGraph agent of plan 8.10: each message is a new
    search through the same pipeline as `GET /api/search`. "More like #2" or "who works with her?" are
    searched as plain text.
  - `filters` replaces the session's filters; without it, the session keeps the last ones. A blank
    `message` with `filters` re-runs the last query (`422` if the session has none yet).
  - `reply` is a template: `"Showing <n> results for '<query>' (source: dcb, type: person)."`.
    The response also has `filters` (the ones the server used) and `expansion`.
  - Sessions live in the API's memory: they are lost when the API restarts, except case sessions
    (`case-<id>`), which are stored (see "Cases").
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

- `follow_outbound: true` means the crawler may also follow links to other hosts (host names only).
- While `status` is `crawling`, the frontend polls `GET /api/sources/{id}` every second and draws
  `discovered` (`{url, parent, depth, status}`) as a live graph: the first 60 URLs the crawler met, in
  crawl order. `queued` URLs left when the page cap is reached end as `skipped`.
- `pages`, `entities`, `verified_claims` map to the counts from `navigator stats` / `GET /api/stats`.
- `validated` means the source is in `config/sources.yaml`, and `root_url` is its first seed. Sources
  crawled before #55 have no recorded tree: `discovered` is then their stored pages as seeds.

`POST /api/sources` (#55) stores the source (`validated: false`) and returns at once with
`status: "crawling"`. The ingest then runs in the background, and `stage` says which step is running:
`crawl` → `embed` → `extract` → `resolve` → `judge`, then `status: "ready"` (minutes: extraction and the
judge call the LLM, and the judge re-checks every source because resolve rebuilds all claims).

- Server caps: 50 pages, depth 4, robots.txt and a 1 s delay per host. One ingest at a time: `409` while
  one runs.
- `422` for a URL that is not http(s), not a public host name, or resolves to a private address.
- Id from the host (`www.example.unibe.ch` → `example_unibe`, then `_2` …). Adding the same site again
  after a failure reuses the failed source.
- `status: "failed"` with `error` (`"<stage>: <message>"`): its pages are deleted, the crawl graph stays.
  A judge error leaves the source `ready`, with `error` set.
- Its crawl rules are stored in `source.config` (the database), not in `config/sources.yaml`.
- **Shared backend:** a new source is written to the backend's database, so every teammate sees it, and
  it changes the eval numbers. Try it on a separate stack first.

## Resources: ranked pages and crawl rules

The Sources page has a "Ranked pages" tab: every crawled page, ranked by what it gives the search,
with actions to block or prioritise pages.

- Served since #78: `GET /api/pages` and `/api/pages/{id}` (read-only, ~20 ms for 100 pages).
  `status` is always `"crawled"` (failed fetches are not stored). `kind` comes from the URL
  (`/team/`, `group_members` → team; `/project/` → project; `/services/` → infrastructure; `_lab/` → lab),
  else `team` when most shown claims are about people, else `other`. Feedback counts 👍/👎 on entities
  with a shown claim on the page. `blocked_by` / `prioritised_by` read the source's current rules (#79).
  A blocked page keeps its counts here, so the table still shows what blocking it hides.
- Served since #79: `GET`/`PUT /api/sources/{id}/rules`; since #80: `POST /api/sources/{id}/crawl`.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | `/api/pages` | – | `ResourcePage[]` (all sources, any order; the UI sorts) |
| GET | `/api/pages/{id}` | – | `PageDetail` = `ResourcePage` + `facts: PageFact[]` |
| GET | `/api/sources/{id}/rules` | – | `CrawlRules` |
| PUT | `/api/sources/{id}/rules` | `{allow_hosts, include_patterns, exclude_patterns, priority_patterns}` | `CrawlRules` |
| POST | `/api/sources/{id}/crawl` | – | `Source` with `status: "crawling"` (re-crawl and ingest, #80) |

**Page score (0–100)**, from data that already exists. `score_breakdown` holds the four parts as
`ScoreItem`s (criterion, 0–100, one-sentence rationale), in this order:

| Part | Weight | Value |
|---|---|---|
| Yield | 40 % | shown claims from the page, `min(100, claims / 40 × 100)` |
| Precision | 30 % | share of the page's judged claims with `judge_verdict = 'supported'` |
| Verification | 20 % | `1 − drop rate`: share of `raw_claim`s from the page that passed quote verification |
| Feedback | 10 % | `(up + 1) / (up + down + 2)` over feedback on results that cite the page |

A failed fetch scores 0 on the first three parts. The same numbers come back as plain fields
(`verified_claims`, `entities`, `judge_supported`, `drop_rate`, `feedback_up`, `feedback_down`),
plus `kind` (`team` | `lab` | `project` | `infrastructure` | `other`, a guess from the URL or the
entity types on the page is fine).

**Rules** default to the source's block in `config/sources.yaml` (or its stored config, for a source
added from the UI); a `PUT` stores all four lists, which then replace the defaults, also for
`navigator crawl` and the re-crawl. Patterns are regular expressions matched with `re.search` on the URL (the UI only uses syntax JavaScript shares). The UI writes:

- *Block* → `^<escaped url>$` added to `exclude_patterns`. *Block similar…* → a pattern the user
  edits, prefilled with the page's folder (`^https://host/path/`).
- *Prioritise* → `^<escaped url>$` added to `priority_patterns`.
- *Unblock* / *Remove priority* → removes the matching rule (the UI warns when it covers more pages).

Expected behaviour:

- **A block applies at once:** search, chat, case references, `/api/stats` and `navigator eval` drop
  claims and relations from pages that match an exclude pattern, without a re-crawl (each claim row
  has one page, so the same fact from another page stays). An entity with no shown claim left is
  dropped. Each `ResourcePage` returns the matching pattern in `blocked_by` (and `prioritised_by`), or
  `null`. Case scores computed before a block are not recomputed.
- Rules are stored in the database (`source_rules`), not lost on restart. `changed_at` is set on every
  PUT (`null` while the defaults apply); when it is newer than the source's `last_crawled_at`, the UI
  offers a re-crawl. Include, priority and host rules only change the next crawl.
- **Re-crawl** (`POST /api/sources/{id}/crawl`, #80): the same background ingest as adding a source, with
  the source's current rules (stored, else `sources.yaml`; its own page budget; priority patterns first),
  and `stage` / `discovered` as there. `404` for an unknown source, `409` while another ingest runs.
  The crawl, embeddings and extraction run in memory; pages, chunks and facts are swapped in at the end,
  in one transaction. So search serves the previous data until then, and a failed run (including more than
  half the pages failing extraction) keeps it: `status: "failed"`, previous pages and facts intact.
  `last_crawled_at` moves on success. Pages excluded by the rules are not fetched, so they leave `GET
  /api/pages`. The judge then re-checks every source (resolve rebuilds all claims): minutes.
- `422` names the list and the pattern that does not compile (`exclude_patterns: invalid regex '(x': …`),
  or says `allow_hosts` is empty for a source that has no host regex. `404` for an unknown source.
- **Shared backend:** a block hides facts for every teammate at once.
