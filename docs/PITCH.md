# Pitch and demo script

Numbers come from `eval/report.md` (9 gold queries, 100 pages; run after #44) and `navigator stats`. Re-run
`uv run navigator eval` before presenting and update the numbers here.

## Slides (5 minutes)

1. **The problem.** Expertise in Bern is spread over hundreds of faculty, institute, lab and centre pages, and
   people search with other words than the sites use ("glucose sensors" vs "continuous glucose monitoring").
2. **What we built.** One search over ARTORG, Diabetes Center Berne and UniBE labs. It returns people and
   units with role, affiliation, expertise, projects and infrastructure, and links every fact to its page.
3. **The guarantee: no invented facts.**
   - Apertus must give a quote for every fact. The quote is matched against the stored page and saved as the
     exact page text, or the fact is rejected.
   - 13% of extracted facts were rejected (221 / 1,705), among them people the model made up from the prompt
     example and list labels like "Alumni".
   - Traceability in the eval: **100%** of displayed facts are verified and link to their source.
4. **Results (honest).**
   - recall@10: **46%** (target 80%), up from 14% after ranking work. Best on cardio (75–100% for 2 of 3
     phrasings), weakest on "implant materials" (0%: the 100-page crawl has little on it).
   - Synonyms: "glucose sensors" and "continuous glucose monitoring" find the same experts (69% overlap of the
     top 10).
   - Field fill for people: role 98%, affiliation 100% (249 people linked to their lab from member pages).
     79% of people show **their lab's topics**, labelled as the lab's and linked to the lab page. Personal
     expertise is 0%: the pages state topics for labs, not for each person, and we don't pretend otherwise.
   - Precision (LLM judge, PoC): 59% of the top-10 results judged relevant; the judge agrees with the human
     gold set on 80% of gold hits.
5. **Sovereign and cheap to run.** Apertus (Swiss open LLM), local bge-m3 embeddings, Postgres, one
   `docker compose` setup with no connection to cantonal networks. Extraction runs on Apertus 8B (70B was slower
   and, measured on the same pages, not better); quote verification is what makes the small model safe to use. A new site is
   one config block (`config/sources.yaml`).
6. **Next.** Scale from 100 to ~2,000 pages (config only, crawling personal profile pages for person-level
   expertise), recall from 46% towards 80%, and the same pipeline for company location reports: suppliers,
   manufacturers and advisors in Canton Bern, with every claim sourced.

## Demo (3 minutes)

Before the demo: `docker compose up -d app frontend` (wait until `app` is healthy: it loads bge-m3 at start),
open http://localhost:5173, and run each query once to warm the query-expansion cache (Apertus calls).

1. **Lay term → experts.** Search `glucose sensors`. Show the "search terms used" panel (CGM, biosensing, German
   terms) and a Diabetes Center Berne result.
2. **Same experts, other words.** Search `continuous glucose monitoring`. The same top 5 comes back (checked:
   Liom Health AG, UDEM, SmartStart Health, Melissa Holloway, DCB Research AG).
3. **Traceability.** Open a result's evidence. Read one quote, click the source link, and find the same sentence
   on the live page. The "wrong fact" button next to each row logs feedback without changing anything.
4. **Affiliation and lab topics.** Search `surgical robots`. A person card (e.g. Manuela Eugster) shows her lab
   from its member page, and "Topics of Neuro Robotics Group" with the lab page as source.
5. **Honest "no result".** Search `quantum cryptography`: no reliable source is found, and nothing is made up.
6. **Add a source** (optional, if time): show one block in `config/sources.yaml` and
   `navigator ingest --source <id>`.

## Questions to expect

- *Why 8B and not 70B?* We measured both on the same 100 pages. 70B was slower (15 vs ~10 min) and not
  better: recall@10 43% vs 46%, judged precision 46% vs 63%. Every fact still has to pass the quote check, and
  switching is one setting (`EXTRACT_MODEL`).
- *How do you know a quote supports the fact?* The quote check proves the text is on the page. Whether it
  supports the fact is checked by an LLM judge (PoC), which is the same model family and therefore biased.
  We report it as a signal, not as proof (judge agreement with the gold set: 80%).
- *Personal data?* Only public pages, only facts written there, each linked to its source; replaced on every
  re-crawl. See "Data protection" in the README.
