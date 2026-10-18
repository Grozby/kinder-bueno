# Pitch and demo script

Numbers come from `eval/report.md` (9 gold queries, 100 pages; last run on 2026-10-18 on main `ad33a2a`,
after #130) and `navigator stats`. Re-run `uv run navigator eval` before presenting and update the numbers here,
in `docs/REPORT.md` and in the slides. Demo timings were measured on the Docker setup on 2026-10-18 (rehearsal, #34), and the script was
rehearsed again three times on a fresh stack restored from `checkpoints/demo.dump`, on main after #95.

## Slides (5 minutes)

1. **The problem.** Expertise in Bern is spread over hundreds of faculty, institute, lab and centre pages, and
   people search with other words than the sites use ("glucose sensors" vs "continuous glucose monitoring").
2. **What we built.** One search over ARTORG, Diabetes Center Berne and UniBE labs. It returns people and
   units with role, affiliation, lab topics, projects and infrastructure, and links every fact to its page.
   On top of it, a **case board**: upload a company's business model PDF, and Apertus reads its needs, scores
   how well Bern's research fits, proposes 25 references, and writes a pitch that cites only verified facts.
3. **The guarantee: no invented facts.**
   - Apertus must give a quote for every fact. The quote is matched against the stored page and saved as the
     exact page text, or the fact is rejected.
   - 13% of extracted facts were rejected (221 / 1,705), among them people the model made up from the prompt
     example and list labels like "Alumni".
   - Traceability in the eval: **100%** of displayed facts are verified and link to their source.
4. **Results (honest).**
   - recall@10: **64%** (target 80%), lay-term phrasings 67%, up from 14% after ranking work. Best on cardio
     (80–100% for all 3 phrasings), weakest on surgery (29–43%: the image-guided therapy chair's head is not in
     the 100 crawled pages).
   - Synonyms: the three glucose phrasings share 60% of their top 10 on average; "glucose sensors" and
     "continuous glucose monitoring" both find Lilian Witthauer, Stavroula Mougiakakou and her AI in Health and
     Nutrition lab.
   - Field fill for people: role 100%, affiliation 100% (249 people linked to their lab from member pages).
     98% of people show **their lab's topics**, labelled as the lab's and linked to the lab page. Personal
     expertise is 0%: the pages state topics for labs, not for each person, and we don't pretend otherwise.
   - Precision (LLM judge, PoC): 49% of the top-10 results judged relevant (60% before the last ranking
     change, #130). The judge sees all 10 results at once, and its verdicts depend on their order: reversing it
     changes 16% of them. It agrees with the human gold set on
     only 61% of gold hits, so treat this as a signal, not a measurement.
5. **Sovereign and cheap to run.** Apertus (Swiss open LLM), local bge-m3 embeddings, Postgres, one
   `docker compose` setup with no connection to cantonal networks. Extraction runs on Apertus 8B (70B was slower
   and, measured on the same pages, not better); quote verification is what makes the small model safe to use. A new site is
   one config block (`config/sources.yaml`).
6. **Next.** Scale from 100 to ~2,000 pages (config only; profile and facility pages for person-level
   expertise), recall from 64% towards 80%, and widen the case board from research partners to suppliers,
   manufacturers and advisors in Canton Bern, with every claim sourced.

## Demo (4 minutes)

**Before the demo** (README "Demo"):
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
   lands in "New" with a **fit score of about 55–80**: Apertus reads the PDF afresh on each upload, and the
   needs it reads move the score (80 in the first rehearsal; 61, 56 and 61 in the later ones, with research fit
   "2 of 5 needs covered"). Read the summary (needle-free wearable glucose sensor, Swiss R&D in
   Bern) and the breakdown: "4 of 5 needs covered … Not covered: wearable biosensor signal processing". Say it:
   the score only counts what our sources prove, and it shows the gap.
2. **References.** Open the card: 25 references, the first 10 preselected. Point at the two kinds of "why":
   "Matches 'closed-loop artificial pancreas systems': …" (a verified topic claim matches a need, so it counts
   in the score) and "Found for '…'" (the search found it, but no claim matches, so it does not count).
3. **Traceability.** Open Prof. Lilian Witthauer's evidence. Each row is a quote from a public page, e.g. her
   role from dcberne.com/en/team/. Click the link and find the same text on the live page. The flag button on a
   row reports a wrong fact; nothing is changed automatically.
4. **Refine with chat.**
   - `continuous glucose monitoring`, then `glucose sensors`: other words, same core (DCB Research AG, AI in
     Health and Nutrition, University Clinic for Diabetology). Apertus expands each query with synonyms and
     German terms (e.g. CGM, biosensors) before searching.
   - `quantum cryptography`: "Showing 0 results": no reliable source, so nothing is made up.
5. **Pitch** (~10 s). Deselect a weak reference (e.g. Acoustic Robotics Systems Lab: "Found for", no matching
   claim), move the card to "Accepted", generate the pitch. Statements about references carry claim ids like
   [11218] that point to the evidence rows; sentences about references that cite nothing, or cite facts outside the
   selection, are removed.
6. *(Optional)* **Honest "no fit".** Drop `vinora-business-model.pdf` (agritech, ~20 s): fit score **0**,
   every criterion 0, "No matching experts in our sources", and the references say "No references in our sources
   match these needs" (#110): nothing is preselected, so no pitch is offered for a case we can't serve.
7. *(Optional)* **Sources** page: the crawl graph, then "Ranked pages": the 100 pages ranked by verified
   facts, judge rate and feedback. Block a page (the ⊘ button): "It no longer appears in results", and its
   facts leave search and cases at once (#79). Press "Undo" in the toast right away. Don't start a re-crawl
   (#80): it re-fetches and re-extracts the whole source, which takes minutes.

**If something is slow:** a search takes ~3–4 s (ranking ~1 s, plus Apertus calls for expansion and the
"why" text); the gateway is shared with other teams. If it stalls, say so and switch to the next step.

## Questions to expect

- *Why 8B and not 70B?* We measured both on the same 100 pages. 70B was slower (15 vs ~10 min) and not
  better: recall@10 43% vs 46%, judged precision 46% vs 63%. Every fact still has to pass the quote check, and
  switching is one setting (`EXTRACT_MODEL`).
- *Why is recall 64% and not 80%?* Every gold expert is in the database; the misses are people ranked 11th to
  40th behind their own lab, and one head whose member page is not crawled. A cross-encoder reranker adds 1 to
  3 experts but takes 7–11 s per search on a CPU, so it is off. A deeper crawl with profile pages (#75, 340
  pages) reaches 58% today: the resolver keeps a few duplicates there, which are the next fix.
- *How do you know a quote supports the fact?* The quote check proves the text is on the page. Whether it
  supports the fact is checked by an LLM judge (PoC), which is the same model family and therefore biased.
  We report it as a signal, not as proof (judge agreement with the gold set: 61–73%).
- *How is the fit score computed?* Five fixed criteria: research fit (40%, share of needs covered), expert
  pool, research units, infrastructure and running projects. Each counts only references whose verified
  topic claims match a need. It measures fit within our sources, not all of Canton Bern.
- *Can the pitch invent things?* A sentence that cites a fact outside the selected references, or names a
  reference without citing it, is removed before the pitch is shown. Limit: a general sentence that names no
  reference ("Bern offers the ecosystem you need") is kept and not checked.
- *Personal data?* Only public pages, only facts written there, each linked to its source; replaced on every
  re-crawl. See "Data protection" in the README.
