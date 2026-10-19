"""Sales pitch for an accepted case (FRONTEND_API "Cases", #54): Apertus writes it from the selected
references' shown claims, every sentence about a reference cites claim ids, citations are checked.

Same approach as the 'why it matches' sentences (explain.py, plan 8.6), on the whole text:
- a sentence that cites an id outside the selected references' claims, cites a lab topic without
  naming the lab, or copies a row ("expertise: …") is removed;
- a sentence that names a reference without citing it is removed;
- if no cited sentence is left (or the gateway fails or is slow), the pitch is a template that lists
  the references and their topics, with citations.

Limit: an uncited sentence that names no reference is kept (greetings, "we would be happy to introduce
you"). The prompt forbids facts that are not listed, but a general claim about Bern there is not checked.
"""

import asyncio
import logging
import re
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from navigator.explain import _flat, _label, check_sentence, cited_ids, prompt_claims
from navigator.llm import LLM
from navigator.models import Evidence, Pitch, Result

log = logging.getLogger(__name__)

TIMEOUT = 30.0
MAX_REFERENCES = 15  # in the prompt; the template lists all of them
MAX_QUOTE = 150
MAX_TOKENS = 1200

SYSTEM = """You write a short sales pitch from the Bern economic development agency to a company:
why Canton Bern is a good place for it, based on the listed references in Bern.
Write 3 to 5 short paragraphs, addressed to the company's team. Plain text, no headings, no lists.
Use ONLY the facts listed for the references. Do not add facts, numbers or names.
Every sentence about a reference MUST cite the claim ids it uses in square brackets, like [12][15].
A sentence about a reference without a claim id is thrown away.
Claim ids are ONLY the numbers in square brackets before each fact, never anything else.
Write natural sentences: do not copy the list, the field names or the quotes.
A "lab topic (via <unit>)" is a topic of the person's unit, NOT the person's own expertise:
write "in <unit>, which works on ..." and name the unit.
Return ONLY JSON: {"pitch": "<text, paragraphs separated by a blank line>"}

Example:
Company: Glucora (medical devices)
Summary: Glucora builds a patch that measures glucose without a needle.
Needs: glucose sensors; clinical studies
References:
- Anna Muster (person)
  [12] role: Group Head — "Anna Muster, Group Head"
  [15] expertise: glucose sensors — "develops glucose sensors for type 1 diabetes"
- Diabetes Lab (unit)
  [21] description: diabetes technology research — "research on diabetes technology"
Answer: {"pitch": "Dear Glucora team,\\n\\nBern has the expertise your needle-free patch needs. Anna Muster, a group head, develops glucose sensors for type 1 diabetes [12][15]. The Diabetes Lab does research on diabetes technology [21].\\n\\nWe would be happy to introduce you."}"""

# "… sensors. [12]" keeps its citation; "Dr. Muster" and "Prof. Dr. …" are not sentence ends
SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\bDr\.)(?<!\bProf\.)(?<!\bPD\.)(?<!\be\.g\.)(?<!\bi\.e\.)\s+(?!\[)")


def format_prompt(company: str, industry: str | None, summary: str | None, needs: list[str],
                  results: list[Result]) -> str:
    blocks = []
    for r in results[:MAX_REFERENCES]:
        rows = [f'  [{e.claim_id}] {_label(e)}: {_flat(e.value)} — "{_flat(e.quote)[:MAX_QUOTE]}"'
                for e in prompt_claims(r.evidence)]
        # No entity id in the header: Apertus cites it as if it were a claim id
        blocks.append("\n".join([f"- {r.name} ({r.type})", *rows]))
    lines = [f"Company: {company}" + (f" ({industry})" if industry else "")]
    if summary:
        lines.append(f"Summary: {_flat(summary)}")
    if needs:
        lines.append("Needs: " + "; ".join(needs))
    return "\n".join(lines) + "\nReferences:\n" + "\n".join(blocks)


def allowed_claims(results: list[Result]) -> dict[int, Evidence]:
    """The claim ids a pitch may cite: those shown in the prompt."""
    return {e.claim_id: e for r in results[:MAX_REFERENCES] for e in prompt_claims(r.evidence)}


def _names(results: list[Result]) -> list[str]:
    """Lower-cased names that mark a sentence as being about a reference: the full name, and a
    person's surname (the pitch often says "Dr. Muster")."""
    names = set()
    for r in results:
        names.add(" ".join(r.name.split()).lower())
        if r.type == "person" and len(surname := r.name.split()[-1]) >= 4:
            names.add(surname.lower())
    return sorted(names)


def check_pitch(text: object, results: list[Result]) -> str | None:
    """The pitch with unchecked sentences removed, or None if no cited sentence is left."""
    if not isinstance(text, str):
        return None
    claims = allowed_claims(results)
    names = _names(results)
    paragraphs, cited = [], 0
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        kept = []
        for sentence in SENTENCE_END.split(" ".join(paragraph.split())):
            if cited_ids(sentence):
                if checked := check_sentence(sentence, claims):
                    kept.append(checked)
                    cited += 1
            elif not any(re.search(rf"\b{re.escape(n)}\b", sentence.lower()) for n in names):
                kept.append(sentence)
        if kept:
            paragraphs.append(" ".join(kept))
    return "\n\n".join(paragraphs) if cited else None


def template(company: str, results: list[Result]) -> str:
    """The fallback: each reference with up to two topics, cited."""
    lines = []
    for r in results:
        rows = [e for e in prompt_claims(r.evidence) if e.field in ("expertise", "description")][:2]
        topics = ", ".join(f"{_flat(e.value)} [{e.claim_id}]" for e in rows)
        lines.append(f"- {r.name}" + (f": {topics}" if topics else ""))
    return (f"Dear {company} team,\n\nThese partners in Canton Bern fit your business:\n\n"
            + "\n".join(lines) + "\n\nWe would be happy to introduce you.")


async def write_pitch(llm: LLM, company: str, industry: str | None, summary: str | None, needs: list[str],
                      results: list[Result], timeout: float = TIMEOUT) -> str:
    """The checked pitch, or the template on a gateway failure, a timeout or no valid citation."""
    if not any(prompt_claims(r.evidence) for r in results[:MAX_REFERENCES]):
        return template(company, results)
    prompt = format_prompt(company, industry, summary, needs, results)
    try:
        data = await asyncio.wait_for(llm.chat_json(SYSTEM, prompt, max_tokens=MAX_TOKENS), timeout)
    except Exception as exc:  # noqa: BLE001 - any LLM or network error falls back to the template
        log.warning("pitch for %r failed: %s", company, exc)
        return template(company, results)
    checked = check_pitch(data.get("pitch"), results)
    if checked is None:
        log.warning("pitch for %r had no valid citation, using the template", company)
        return template(company, results)
    return checked


def case_context(conn: psycopg.Connection, case_id: str) -> tuple[str, str | None, str | None, list[str]] | None:
    """Company name, industry, summary and needs (search queries from the analysis, #53)."""
    row = conn.execute('SELECT company_name, industry, summary, needs FROM "case" WHERE id = %s', (case_id,)).fetchone()
    return (row[0], row[1], row[2], [str(n) for n in row[3]]) if row else None


def unknown_entities(conn: psycopg.Connection, entity_ids: list[int]) -> list[int]:
    found = {r[0] for r in conn.execute("SELECT id FROM entity WHERE id = ANY(%s)", (entity_ids,))}
    return [i for i in entity_ids if i not in found]


def save_pitch(conn: psycopg.Connection, case_id: str, text: str, entity_ids: list[int]) -> Pitch:
    pitch = Pitch(text=text, entity_ids=entity_ids, generated_at=datetime.now(UTC))
    conn.execute('UPDATE "case" SET pitch = %s WHERE id = %s', (Jsonb(pitch.model_dump(mode="json")), case_id))
    return pitch


def load_pitch(conn: psycopg.Connection, case_id: str) -> Pitch | None:
    row = conn.execute('SELECT pitch FROM "case" WHERE id = %s', (case_id,)).fetchone()
    return Pitch(**row[0]) if row and row[0] else None
