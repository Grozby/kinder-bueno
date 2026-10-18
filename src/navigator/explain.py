"""'Why it matches' sentences (plan 8.6): one Apertus call per top result, in parallel, citations checked.

Not one call for all ten (plan 8.6): Apertus then answers only the 1-5 results it finds strongest
(10 of 40 on 4 test queries). One small call per result answered 40 of 40 in ~2 s.

A sentence is kept only if it cites at least one claim id and every cited id is one of that result's
claims shown in the prompt. Anything else falls back to the template in results.py.

People often match through their lab: their evidence then has rows with `via_unit` (#44), the lab's
topics, not theirs. The prompt labels them "lab topic (via <unit>)", and a sentence citing one must
name that unit, so a lab topic is never presented as personal expertise.
"""

import asyncio
import logging
import re

from navigator.llm import LLM
from navigator.models import Evidence, Result

log = logging.getLogger(__name__)

TIMEOUT = 15.0  # seconds for all calls; on the query path, so a slow gateway falls back to the template
MAX_RESULTS = 10
MAX_CLAIMS = 10  # per result; a big unit has 120+
MAX_QUOTE = 150
FIELD_ORDER = ("expertise", "unit_expertise", "description", "role", "name")  # most explanatory first
SKIP_FIELDS = ("email", "phone")  # contact data explains nothing

SYSTEM = """For each result, write ONE short sentence that explains why it matches the query.
Use ONLY the facts listed for that result. Do not add facts.
Every sentence MUST cite the claim ids it uses in square brackets, like [12][15].
A sentence without a claim id is thrown away. Write a sentence for EVERY result.
Write a natural sentence: do not copy the list, the field names or the quotes.
A "lab topic (via <unit>)" is a topic of the person's unit, NOT the person's own expertise:
write "in <unit>, which works on ..." and name the unit. Never say the person has that expertise.
Return ONLY JSON: {"<entity_id>": "<sentence>", ...}
Use the number at the start of each result as the key, without the name.

Example:
Query: glucose sensors
Results:
7 Anna Muster (person)
  [12] role: Group Head — "Anna Muster, Group Head"
  [15] expertise: glucose sensors — "develops glucose sensors for type 1 diabetes"
9 Diabetes Lab (unit)
  [21] description: diabetes technology research — "research on diabetes technology"
4 Ben Beispiel (person)
  [30] role: PhD student — "Ben Beispiel, PhD student"
  [31] lab topic (via Sensor Lab): continuous glucose monitoring — "The Sensor Lab works on CGM."
Answer: {"7": "Group Head who develops glucose sensors [12][15].",
         "9": "Does research on diabetes technology [21].",
         "4": "PhD student in the Sensor Lab, which works on continuous glucose monitoring [30][31]."}"""

CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def prompt_claims(evidence: list[Evidence]) -> list[Evidence]:
    """The claims shown to the model: explanatory fields first, no contact data, at most MAX_CLAIMS."""
    rank = {f: i for i, f in enumerate(FIELD_ORDER)}
    usable = [e for e in evidence if e.field not in SKIP_FIELDS]
    return sorted(usable, key=lambda e: rank.get(e.field, len(FIELD_ORDER)))[:MAX_CLAIMS]


def _flat(text: str) -> str:
    """One line: page text keeps its line breaks, which would break the numbered list."""
    return " ".join(text.split())


def _label(e: Evidence) -> str:
    return f"lab topic (via {e.via_unit})" if e.via_unit else e.field


def format_results(query: str, results: list[Result]) -> str:
    blocks = []
    for r in results:
        rows = [f'  [{e.claim_id}] {_label(e)}: {_flat(e.value)} — "{_flat(e.quote)[:MAX_QUOTE]}"'
                for e in prompt_claims(r.evidence)]
        blocks.append("\n".join([f"{r.entity_id} {r.name} ({r.type})", *rows]))
    return f"Query: {query}\nResults:\n" + "\n".join(blocks)


def cited_ids(sentence: str) -> set[int]:
    """Claim ids in "[12][15]" or "[12, 15]" form."""
    return {int(n) for group in CITATION.findall(sentence) for n in group.split(",")}


ECHO = re.compile(r"\b(unit_expertise|lab topic|expertise|description|role|name)\s*:", re.IGNORECASE)


def check_sentence(sentence: object, claims: dict[int, Evidence]) -> str | None:
    """The sentence if it cites at least one id, only ids in `claims`, names the unit of every cited
    lab topic, and does not copy rows ("unit_expertise: …"); otherwise None (use the template)."""
    if not isinstance(sentence, str) or not sentence.strip():
        return None
    text = " ".join(sentence.split())
    cited = cited_ids(text)
    if not cited or not cited <= claims.keys() or ECHO.search(text):
        return None
    units = {claims[i].via_unit for i in cited if claims[i].via_unit}
    if any(" ".join(u.split()).lower() not in text.lower() for u in units):
        return None
    return text


def parse_why(data: dict, results: list[Result]) -> dict[int, str]:
    """Checked sentences by entity id. Keys may carry the name after the id ("4 ARTORG Center")."""
    allowed = {r.entity_id: {e.claim_id: e for e in prompt_claims(r.evidence)} for r in results}
    why = {}
    for key, sentence in data.items():
        m = re.match(r"\s*(\d+)\b", str(key))
        entity_id = int(m.group(1)) if m else None
        if entity_id in allowed and (checked := check_sentence(sentence, allowed[entity_id])):
            why[entity_id] = checked
    return why


async def _ask(llm: LLM, query: str, result: Result) -> dict[int, str]:
    data = await llm.chat_json(SYSTEM, format_results(query, [result]), max_tokens=200)
    return parse_why(data, [result])


async def explain(llm: LLM, query: str, results: list[Result], timeout: float = TIMEOUT) -> dict[int, str]:
    """Checked 'why' sentences by entity id; missing ids (failure, timeout, bad citation) use the template.
    Calls that finish within `timeout` are kept, the rest are cancelled."""
    todo = [r for r in results[:MAX_RESULTS] if prompt_claims(r.evidence)]
    if not todo:
        return {}
    tasks = [asyncio.create_task(_ask(llm, query, r)) for r in todo]
    done, pending = await asyncio.wait(tasks, timeout=timeout)
    for task in pending:
        task.cancel()
    why: dict[int, str] = {}
    failed = len(pending)
    for task in done:
        if task.exception():  # LLM or network error: that result keeps the template
            failed += 1
            log.warning("explanation failed for %r: %s", query, task.exception())
        else:
            why.update(task.result())
    log.info("explanations for %r: %d kept, %d failed or late, of %d", query, len(why), failed, len(todo))
    return why


def apply_why(results: list[Result], why: dict[int, str]) -> list[Result]:
    """Results with the checked sentences; the others keep the template from build_results."""
    return [r.model_copy(update={"why": why[r.entity_id]}) if r.entity_id in why else r for r in results]
