"""Page → claims and relations, each with a quote, then quote verification (PLAN 7.5, 7.6)."""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ValidationError, field_validator

from navigator.llm import LLM, LLMError
from navigator.resolve import is_person_name, norm_name
from navigator.verify import PageText, verify_claim, verify_relation

log = logging.getLogger(__name__)

MAX_PART_CHARS = 6_000  # dense team pages produce long answers; smaller parts keep them complete
MAX_ANSWER_TOKENS = 12_000  # people prompt: long member lists
MAX_TOPICS_TOKENS = 4_000   # topics answers are short; on member lists 8B loops, so fail fast

FIELDS: dict[str, set[str]] = {
    "person": {"name", "role", "email", "phone", "expertise", "bio"},
    "unit": {"name", "unit_type", "description", "expertise"},
    "project": {"name", "description", "expertise"},
    "infrastructure": {"name", "description"},
}
RELATIONS: dict[str, tuple[set[str], set[str]]] = {
    "member_of": ({"person"}, {"unit"}),
    "part_of": ({"unit"}, {"unit"}),
    "works_on": ({"person", "unit"}, {"project"}),
    "provides": ({"unit"}, {"infrastructure"}),
}

_COMMON = """You extract facts from one web page of a research institution.
Return ONLY a JSON object. No other text.

Entity types and their ONLY allowed fields:
- person: name, role, email, phone, expertise, bio
- unit (faculty, department, institute, center, lab, group, team): name, unit_type, description, expertise
- project (research project, study, programme): name, description, expertise
- infrastructure (equipment, facility, platform, service offered to others): name, description
Use no other entity types or fields. Skip facts that do not fit (addresses, websites, dates, funding).

Relations (ONLY these):
- member_of: person -> unit
- part_of: unit -> unit
- works_on: person or unit -> project
- provides: unit -> infrastructure

Quote rules:
- Only extract facts that are written on the page. Do not guess. Do not add knowledge.
- "quote" MUST be copied EXACTLY from the page text: one CONTIGUOUS piece of text, max 300 characters.
  Do not join text from different places. Do not shorten, fix, translate or reformat it.
  It may span several lines.
- "value" is the fact in short form. For name, role, email, phone: value MUST appear inside the quote.

JSON format: one row (array) per claim and per relation, to keep the answer short.
{"claims": [[entity_type, entity_name, field, value, quote], ...],
 "relations": [[from_type, from_name, rel, to_type, to_name, quote], ...]}
If there is nothing to extract, return {"claims": [], "relations": []}.
"""

PEOPLE_PROMPT = _COMMON + """
YOUR TASK: extract ONLY people (entity_type "person") and their relations. Ignore everything else.
- Be complete: include EVERY named person on the page. Only real named people, not "info@..." contacts.
- For each person: a role claim (quote = the lines from the name to the role, or from the role to
  the name), and an email and a phone claim when shown. Add a name claim only if no role is shown.
- expertise or bio claims only when a sentence on the page says what this person works on.
- Add a member_of relation from each person to the unit the list belongs to (often named in the page
  title). Its quote is the person's name line. Add works_on when the page says the person works on a project.

Example, member list page "Group Members - Medical Sensing Laboratory" with the text
"Name / Titel\nDr. Lucas Patty\nFunktion\nResearch Associate\nMail\nlucas.patty@unibe.ch":
{"claims": [["person", "Dr. Lucas Patty", "role", "Research Associate", "Dr. Lucas Patty\nFunktion\nResearch Associate"],
            ["person", "Dr. Lucas Patty", "email", "lucas.patty@unibe.ch", "Dr. Lucas Patty\nFunktion\nResearch Associate\nMail\nlucas.patty@unibe.ch"]],
 "relations": [["person", "Dr. Lucas Patty", "member_of", "unit", "Medical Sensing Laboratory", "Dr. Lucas Patty"]]}
"""

TOPICS_PROMPT = _COMMON + """
YOUR TASK: extract ONLY units, projects and infrastructure (NOT people) and the relations between them.
- For each unit, project or infrastructure the page is about: one name claim and one description
  claim (one sentence).
- 2 to 6 expertise claims per unit or project: short topic phrases (2-5 words) taken from the page, like
  "sea ice acoustics" in the example below. The quote is the sentence that shows the topic.
- No research sentence on the page (a team list, contacts, a menu): no expertise or description claims.
  Never use a heading, a name or a label ("Team", "Group Members") as the quote for a topic.
- Relations: part_of (unit -> unit), works_on (unit -> project), provides (unit -> infrastructure).

Example (fictional), lab page with the text "Vemlor Lab\nPolar Acoustics\nOur research is focused on how sound
travels through sea ice and what it reveals about ice thickness.":
{"claims": [["unit", "Vemlor Lab", "name", "Vemlor Lab", "Vemlor Lab"],
            ["unit", "Vemlor Lab", "description", "research on sound propagation through sea ice", "Our research is focused on how sound travels through sea ice and what it reveals about ice thickness."],
            ["unit", "Vemlor Lab", "expertise", "sea ice acoustics", "Our research is focused on how sound travels through sea ice and what it reveals about ice thickness."],
            ["unit", "Vemlor Lab", "expertise", "ice thickness measurement", "Our research is focused on how sound travels through sea ice and what it reveals about ice thickness."]],
 "relations": []}
"""

PROFILE_PROMPT = _COMMON + """
YOUR TASK: is this page ONE person's own profile page (one person, with a CV, "research interests" or a
research description)? If not, return {"claims": [], "relations": []}.
If it is: AT MOST 6 expertise claims for that person, and nothing else. Each is a specific research topic of
2-5 words, like "computer vision", "dietary assessment", "cardiac electrophysiology", taken from the page.
Never single generic words ("research", "health", "technology", "systems", "medical", "engineering"), and
never the name of a group or lab. The quote is the sentence that names the topic.

Example, profile page "Prof. Dr. Xyla Qorvant" with the text
"Prof. Dr. Xyla Qorvant\nGroup Head\nHer research interests include glacier acoustics and lichen genomics.":
{"claims": [["person", "Prof. Dr. Xyla Qorvant", "expertise", "glacier acoustics", "Her research interests include glacier acoustics and lichen genomics."],
            ["person", "Prof. Dr. Xyla Qorvant", "expertise", "lichen genomics", "Her research interests include glacier acoustics and lichen genomics."]],
 "relations": []}
"""

# Profile topics have their own call (#75): in the people prompt they cost member_of relations on list pages
PROMPTS = (
    (PEOPLE_PROMPT, MAX_ANSWER_TOKENS), (TOPICS_PROMPT, MAX_TOPICS_TOKENS), (PROFILE_PROMPT, MAX_TOPICS_TOKENS),
)

EntityType = Literal["person", "unit", "project", "infrastructure"]


def _not_blank(v: object) -> str:
    if not isinstance(v, str):
        raise ValueError("not a string")
    v = v.strip()
    if not v:
        raise ValueError("empty")
    return v


class Claim(BaseModel):
    entity_type: EntityType
    entity_name: str
    field: str
    value: str
    quote: str

    strip_text = field_validator("entity_name", "field", "value", "quote", mode="before")(_not_blank)

    @field_validator("field")
    @classmethod
    def _known_field(cls, v: str, info) -> str:
        if v not in FIELDS.get(info.data.get("entity_type", ""), set()):
            raise ValueError(f"unknown field {v!r}")
        return v


class Relation(BaseModel):
    from_type: EntityType
    from_name: str
    rel: Literal["member_of", "part_of", "works_on", "provides"]
    to_type: EntityType
    to_name: str
    quote: str

    strip_text = field_validator("from_name", "to_name", "quote", mode="before")(_not_blank)

    @field_validator("to_type")
    @classmethod
    def _valid_types(cls, v: str, info) -> str:
        allowed_from, allowed_to = RELATIONS[info.data["rel"]] if "rel" in info.data else (set(), set())
        if info.data.get("from_type") not in allowed_from or v not in allowed_to:
            raise ValueError("entity types do not fit the relation")
        return v


@dataclass
class Checked:
    item: Claim | Relation
    verified: bool
    quote: str
    fail_reason: str | None


@dataclass
class PageResult:
    page_id: int
    claims: list[Checked] = field(default_factory=list)
    relations: list[Checked] = field(default_factory=list)
    dropped: int = 0          # items that failed schema validation
    error: str | None = None  # the whole page failed (LLM error)


def split_text(text: str, max_chars: int = MAX_PART_CHARS) -> list[str]:
    """Split on line breaks into parts of at most max_chars (a single longer line is cut)."""
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.append(line[:max_chars])
            line = line[max_chars:]
        if current and len(current) + 1 + len(line) > max_chars:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


CLAIM_KEYS = ("entity_type", "entity_name", "field", "value", "quote")
RELATION_KEYS = ("from_type", "from_name", "rel", "to_type", "to_name", "quote")


def _as_dict(raw: object, keys: tuple[str, ...]) -> object:
    """Rows (the prompt's compact format) become dicts; dicts pass through."""
    if isinstance(raw, list) and len(raw) == len(keys):
        return dict(zip(keys, raw))
    return raw


# A flat JSON array of strings: one compact row.
_ROW_RE = re.compile(r'\[\s*"(?:[^"\\]|\\.)*"(?:\s*,\s*"(?:[^"\\]|\\.)*")*\s*\]')


def salvage_rows(text: str) -> dict:
    """Recover every complete row from an answer that was cut off (the 8B model sometimes loops
    until max_tokens). Rows are told apart by length: 5 values = claim, 6 = relation."""
    claims, relations, seen = [], [], set()
    for m in _ROW_RE.finditer(text):
        try:
            row = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        key = tuple(row)
        if key in seen:  # loops repeat the same rows
            continue
        seen.add(key)
        if len(row) == len(CLAIM_KEYS):
            claims.append(row)
        elif len(row) == len(RELATION_KEYS):
            relations.append(row)
    return {"claims": claims, "relations": relations}


def parse_items(data: dict) -> tuple[list[Claim], list[Relation], int]:
    """Validate each item on its own: one bad item must not drop the whole page.
    Rows are routed by length, so a relation row inside "claims" is still used."""
    claims, relations, dropped = [], [], 0
    items = [*(data.get("claims") or []), *(data.get("relations") or [])]
    for raw in items:
        is_relation = (isinstance(raw, list) and len(raw) == len(RELATION_KEYS)) or (
            isinstance(raw, dict) and "rel" in raw
        )
        try:
            if is_relation:
                relations.append(Relation.model_validate(_as_dict(raw, RELATION_KEYS)))
            else:
                claims.append(Claim.model_validate(_as_dict(raw, CLAIM_KEYS)))
        except ValidationError:
            dropped += 1
    return claims, relations, dropped


def check_items(page: PageText, claims: list[Claim], relations: list[Relation]) -> tuple[list[Checked], list[Checked]]:
    checked_claims = []
    for c in claims:
        if c.entity_type == "person" and not is_person_name(c.entity_name):
            checked_claims.append(Checked(c, False, c.quote, "not a person name"))
            continue
        m = verify_claim(page, c.entity_name, c.field, c.value, c.quote)
        checked_claims.append(Checked(c, m.ok, m.quote, m.reason))
    checked_relations = []
    for r in relations:
        names = [n for t, n in ((r.from_type, r.from_name), (r.to_type, r.to_name)) if t == "person"]
        if not all(is_person_name(n) for n in names):
            checked_relations.append(Checked(r, False, r.quote, "not a person name"))
            continue
        m = verify_relation(page, r.from_name, r.to_name, r.quote)
        checked_relations.append(Checked(r, m.ok, m.quote, m.reason))
    return checked_claims, checked_relations


def reverify(rows: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    """Re-run the checks on stored raw rows, without LLM calls (after a rule change).

    rows: (kind, id, title, text, *item fields) with kind "claim" or "relation".
    Returns (claim updates, relation updates) as (verified, quote, fail_reason, id)."""
    pages: dict[tuple[str, str], PageText] = {}
    claim_updates, relation_updates = [], []
    for kind, row_id, title, text, *fields in rows:
        page = pages.setdefault((title, text), PageText(f"{title}\n{text}"))
        if kind == "claim":
            item = Claim.model_construct(**dict(zip(CLAIM_KEYS, fields)))
            (checked,), _ = check_items(page, [item], [])
            claim_updates.append((checked.verified, checked.quote, checked.fail_reason, row_id))
        else:
            item = Relation.model_construct(**dict(zip(RELATION_KEYS, fields)))
            _, (checked,) = check_items(page, [], [item])
            relation_updates.append((checked.verified, checked.quote, checked.fail_reason, row_id))
    return claim_updates, relation_updates


async def extract_page(llm: LLM, page_id: int, url: str, title: str, text: str) -> PageResult:
    """Two focused calls per page part (people, topics): one combined prompt skipped one of the two."""
    result = PageResult(page_id)
    page = PageText(f"{title}\n{text}")  # the title is source content too (unit names often live there)

    async def call(system: str, max_tokens: int, part: str) -> dict | None:
        user = f"Page URL: {url}\nPage title: {title}\n\nPage text:\n<<<\n{part}\n>>>"
        try:
            return await llm.chat_json(system, user, max_tokens=max_tokens)
        except LLMError as e:
            salvaged = salvage_rows(e.text)
            n = len(salvaged["claims"]) + len(salvaged["relations"])
            log.warning("salvaged %d rows from a broken answer for %s (%s)", n, url, e)
            if n:
                return salvaged
            result.error = str(e)[:200]
            return None
        except Exception as e:  # one failing call must not stop the run (HTTP errors)
            log.warning("extraction failed for %s: %s", url, str(e)[:200])
            result.error = str(e)[:200]
            return None

    answers = await asyncio.gather(
        *(call(prompt, max_tokens, part) for part in split_text(text) for prompt, max_tokens in PROMPTS)
    )
    for data in answers:
        if data is None:
            continue
        claims, relations, dropped = parse_items(data)
        checked_claims, checked_relations = check_items(page, claims, relations)
        result.claims += checked_claims
        result.relations += checked_relations
        result.dropped += dropped
    return result


async def extract_pages(llm: LLM, pages: list[tuple[int, str, str, str]]) -> list[PageResult]:
    """pages: (page_id, url, title, text). Runs in parallel, bounded by the LLM semaphore."""
    return await asyncio.gather(*(extract_page(llm, *p) for p in pages))
