# Pitch and demo script

Numbers come from `eval/report.md` (gold set v2: 18 queries, 340 pages; last run on 2026-10-19 on main
`458e2f0`, after the database swap) and `navigator stats`. Re-run `uv run navigator eval` before presenting and update the numbers here,
in `docs/REPORT.md` and in the slides. The demo below was re-rehearsed on 2026-10-19 on the 340-page database
(main `eb39e41`, a copy of the shared DB): every step was run through the API, with 4 Glucora uploads. The UI
clicks were last rehearsed on the 100-page database (2026-10-18, #34 and after #95), so click through once more
before presenting.

## Slides (5 minutes)

The deck is [`docs/slides/pitch.html`](slides/pitch.html): 10 slides with speaker notes. Open it in a browser:
the arrow keys page through it, N shows the notes, F goes full screen. Printing it gives one slide per page; the
command is in the file's header. The outline below is the talk
track; the slides use the same numbers.

1. **The problem.** Expertise in Bern is spread over hundreds of faculty, institute, lab and centre pages, and
   people search with other words than the sites use ("glucose sensors" vs "continuous glucose monitoring").
2. **What we built.** One search over ARTORG, Diabetes Center Berne and UniBE labs. It returns people and
   units with role, affiliation, lab topics, projects and infrastructure, and links every fact to its page.
   On top of it, a **case board**: upload a company's business model PDF, and Apertus reads its needs, scores
   how well Bern's research fits, proposes 25 references, and writes a pitch that cites only verified facts.
3. **The guarantee: no invented facts.**
   - Apertus must give a quote for every fact. The quote is matched against the stored page and saved as the
     exact page text, or the fact is rejected.
   - 16% of extracted facts were rejected (820 / 5,263), among them people the model made up from the prompt
     example and list labels like "Alumni".
   - Traceability in the eval: **100%** of displayed facts are verified and link to their source.
4. **Results (honest).**
   - recall@10: **60%** (target 80%) on 18 queries in 6 use cases, lay-term phrasings 61%. Best on cardio (80%
     for all 3 phrasings), weakest on glucose and rehab (33–67%), where some experts are linked only to hospital
     pages.
   - Synonyms: the three phrasings of a use case share 37–62% of their top 10; "glucose sensors" and
     "continuous glucose monitoring" both find the Diabetes Center Berne and the AI in Health and Nutrition lab.
   - Field fill for people: role 100%, affiliation 100% (~790 people linked to their lab from member pages).
     38% of people in the results have **their own expertise**, from their profile pages; the others show their
     lab's topics, labelled as the lab's.
   - Precision (LLM judge, PoC): 86% of the top-10 results judged relevant, each result judged on its own. It
     agrees with the human gold set on 91% of gold hits, but it is the extractor's model family, so treat it as a
     signal, not a measurement.
   - Case board: all 4 example companies score in their expected range; 19 of 31 expected matches found.
5. **Sovereign and cheap to run.** Apertus (Swiss open LLM), local bge-m3 embeddings, Postgres, one
   `docker compose` setup with no connection to cantonal networks. Extraction runs on Apertus 8B (70B was slower
   and, measured on the same pages, not better); quote verification is what makes the small model safe to use. A new site is
   one config block (`config/sources.yaml`).
6. **Next.** Scale from 340 to ~2,000 pages (config only; more profile and facility pages for person-level
   expertise), recall from 60% towards 80%, and widen the case board from research partners to suppliers,
   manufacturers and advisors in Canton Bern, with every claim sourced.

## Demo (4 minutes)

**Before the demo** (README "Demo"):
- The script below needs the 340-page data. `checkpoints/demo.dump` (the `v0.1.1` handoff snapshot) still holds
  the 100 pages: present from the shared stack, or first take a new snapshot with `scripts/demo.sh dump`.
- `docker compose run --rm restore` loads the snapshot (it replaces every case with the snapshot's; take the
  snapshot from a board without a Glucora card, since the demo uploads Glucora live), then
  `docker compose run --rm app uv run navigator init-db` (adds what a snapshot older than the code lacks), then
  `docker compose up -d app frontend`. The app is healthy after ~1 min: it loads bge-m3 and embeds the topic
  claims for ranking.
- In the demo browser, answer the "Welcome to Bern Fit" name prompt beforehand (it opens on the first visit).
- Open http://localhost:5173 and send the three chat queries of step 4 once in any case: query expansion is
  cached per process, so this saves ~2 s per query during the demo.
- Keep `docs/examples/glucora-business-model.pdf` (and `vinora-business-model.pdf` for step 6) ready to drag in.
- Leave out the reviewer score and notes in the drawer: the UI has them, but the backend does not serve them
  yet (`docs/FRONTEND_API.md`, "Review, notes and similar cases").

1. **Upload a company** (~25 s). Drop the Glucora PDF on the board. The pop-up shows the analysis; the card
   lands in "New" with a **fit score of about 60–70**: Apertus reads the PDF afresh on each upload, and the
   needs it reads move the score (60, 69, 69 and 69 in the 340-page rehearsal). Read the summary (needle-free
   wearable glucose sensor, Swiss R&D in Bern) and the breakdown: "4 of 5 needs covered … Not covered:
   biocompatibility testing for skin sensors". Say it: the score only counts what our sources prove, and it
   shows the gap.
2. **References.** Open the card: 25 references; only the 7–10 marked "Matches" are preselected. Point at the
   two kinds of "why": "Matches 'closed-loop artificial pancreas systems': …" (a verified topic claim matches a
   need, so it counts in the score) and "Found for '…'" (the search found it, but no claim matches, so it does
   not count and is never preselected).
3. **Traceability.** Open Dr. med. Dr. phil. Lia Bally's evidence (a preselected reference, rank 7–10). Each row
   is a quote from a public page: her role "Group Leader" from the Bally Lab team page on dbmr.unibe.ch, and her
   lab's "closed-loop automated insulin delivery systems" from the Bally Lab page. Click the link and find the
   same text on the live page. The flag button on a row reports a wrong fact; nothing is changed automatically.
4. **Refine with chat.**
   - `continuous glucose monitoring`, then `glucose sensors` (~3–4 s each): other words, same core (DCB
     Research AG, Diabetes Center Berne, University Clinic for Diabetology, DCB and Tidepool). Apertus expands
     each query with synonyms and German terms (e.g. CGM, biosensors) before searching.
   - `More like #2` (~4–6 s), then `Who works with #2?` (~1 s): the chat agent (#131) reads the numbers as
     earlier results. "More like" Diabetes Center Berne brings DCB and Tidepool, Prof. Lilian Witthauer and
     Prof. Maria Luisa Balmer; then the people linked to the new #2, DCB and Tidepool: Andrea Celoria, Thomas
     Züger, José García-Tirado, Lilian Witthauer. Add one of them as a reference. Use exactly this order:
     `More like #1` after `continuous glucose monitoring` drifts into rehabilitation groups.
   - `quantum cryptography`: "Showing 0 results": no reliable source, so nothing is made up.
5. **Pitch** (~12 s). Only "Matches" references are preselected, so there is no weak one to remove; to show
   the selection, deselect one (e.g. Artificial Intelligence in Medical Imaging). Move the card to "Accepted",
   generate the pitch. Statements about references carry small numbered citations (#109): click one to show the
   cited fact, its quote and the source page. Sentences about references that cite nothing, or cite facts
   outside the selection, are removed.
6. *(Optional)* **Honest "low fit".** Drop `vinora-business-model.pdf` (agritech, ~16 s): fit score **about 12**,
   "1 of 5 needs covered" (a loose one: Dr. Kevin Debeire's "climate science" for "soil science irrigation
   climate adaptation"), the other four needs listed as not covered. Nothing is preselected and "Generate
   pitch" stays disabled: with fewer than 2 needs covered, no pitch is offered (#158). Say it: the score shows
   the gap instead of inventing a fit.
7. *(Optional)* **Sources** page: the crawl graph, then "Ranked pages": the 340 pages ranked by verified
   facts, judge rate and feedback. Block a page (the ⊘ button): "It no longer appears in results", and its
   facts leave search and cases at once (#79). Press "Undo" in the toast right away. Don't start a re-crawl
   (#80): it re-fetches and re-extracts the whole source, which takes minutes.

**If something is slow:** a search takes ~3–4 s (ranking ~1 s, plus Apertus calls for expansion and the
"why" text); the gateway is shared with other teams. If it stalls, say so and switch to the next step.

## Questions to expect

- *Why 8B and not 70B?* We measured both on the same 100 pages. 70B was slower (15 vs ~10 min) and not
  better: recall@10 43% vs 46%, judged precision 46% vs 63%. Every fact still has to pass the quote check, and
  switching is one setting (`EXTRACT_MODEL`).
- *Why is recall 60% and not 80%?* Most misses are gaps in the data, not ranking: some experts are linked only
  to hospital or project pages, not to a lab, so no ranking change brings them in. Ranking constants were swept
  (#144). A cross-encoder reranker adds 1 to 3 experts but takes 7–11 s per search on a CPU, so it is off. The
  number is on a different gold set (18 queries over 340 pages); the earlier 64% was on 9 queries over 100 pages.
- *How do you know a quote supports the fact?* The quote check proves the text is on the page. Whether it
  supports the fact is checked by an LLM judge (PoC), which is the same model family and therefore biased.
  We report it as a signal, not as proof (judge agreement with the gold set: 91%).
- *How is the fit score computed?* Five fixed criteria: research fit (40%, share of needs covered), expert
  pool, research units, infrastructure and running projects. Each counts only references whose verified
  topic claims match a need. It measures fit within our sources, not all of Canton Bern.
- *Can the pitch invent things?* A sentence that cites a fact outside the selected references, or names a
  reference without citing it, is removed before the pitch is shown. Limit: a general sentence that names no
  reference ("Bern offers the ecosystem you need") is kept and not checked.
- *Personal data?* Only public pages, only facts written there, each linked to its source; replaced on every
  re-crawl. See "Data protection" in the README.
