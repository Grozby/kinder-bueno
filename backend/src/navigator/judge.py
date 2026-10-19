"""Claim judge [PoC] (plan 7.8): does the quote support the stated fact?

Quote verification (7.6) proves a quote is on the page, not that it supports the fact. One Apertus
call per page judges that page's verified claims (expertise, description, bio, unit_type) and
verified relations. Verdicts go to judge_verdict / judge_reason; "unsupported" rows are then hidden
(results.shown). A failed call or a missing item leaves the verdict NULL: the judge never blocks.
Resolve rebuilds the claim table, so run the judge after it.
"""

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass

import psycopg

from navigator.core.llm import LLM

log = logging.getLogger(__name__)

JUDGED_FIELDS = ("expertise", "description", "bio", "unit_type")  # name/role/email/phone: value is in the quote (7.6)
VERDICTS = ("supported", "partial", "unsupported")
MAX_ITEMS = 25  # per call, so the answer stays short; bigger pages are split
TIMEOUT = 180.0  # seconds per call
MAX_QUOTE = 400

SYSTEM = """You check facts extracted from one web page of a research institution.
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
- "listed_in" means only: the person appears on this page, which is the member list of that unit.
  It does NOT claim a role or membership. It is "supported" if the quote is this person's own entry.
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
[5] relation: person "Lena Beispiel" listed_in unit "Hearing Research Laboratory"
    quote: "Lena Beispiel, PhD Student"
    → supported (her entry on the member list)

JSON format:
{"verdicts": [{"id": 1, "verdict": "supported|partial|unsupported", "reason": "..."}]}"""


@dataclass(frozen=True)
class Item:
    table: str  # "claim" or "relation"
    row_id: int
    line: str  # e.g. 'person "Anna Muster" — expertise: "surgical robotics"'
    quote: str


@dataclass(frozen=True)
class Page:
    page_id: int
    url: str
    title: str
    items: list[Item]


def _one_line(text: str) -> str:
    return " ".join(text.split())


def format_items(page: Page, items: list[Item]) -> str:
    """User message of plan 7.8; the full page text is not sent (the judge decides from the quote)."""
    lines = [f"Page URL: {page.url}", f"Page title: {page.title}", "", "Items:"]
    for i, item in enumerate(items, start=1):
        lines += [f"[{i}] {item.line}", f'    quote: "{_one_line(item.quote)[:MAX_QUOTE]}"']
    return "\n".join(lines)


def parse_verdicts(data: dict, n_items: int) -> dict[int, tuple[str, str]]:
    """{item number: (verdict, reason)} for valid entries; unknown numbers and verdicts are dropped."""
    rows = data.get("verdicts")
    verdicts = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        m = re.search(r"\d+", str(row.get("id", "")))
        verdict = str(row.get("verdict", "")).strip().lower()
        if m and 1 <= int(m.group()) <= n_items and verdict in VERDICTS:
            verdicts[int(m.group())] = (verdict, _one_line(str(row.get("reason") or "")))
    return verdicts


def batches(items: list[Item], size: int = MAX_ITEMS) -> list[list[Item]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def judge_items(llm: LLM, page: Page, items: list[Item], timeout: float = TIMEOUT) -> dict[Item, tuple[str, str]]:
    """Verdicts for one batch. Any failure gives {} (the verdicts stay NULL). `timeout` is per request, not
    counting the wait for an LLM slot (#148)."""
    try:
        data = await llm.chat_json(SYSTEM, format_items(page, items), max_tokens=2500, timeout=timeout)
    except Exception as e:  # LLM, network or timeout: never block the pipeline
        log.warning("judge failed for %s: %s %s", page.url, type(e).__name__, e)
        return {}
    return {items[i - 1]: v for i, v in parse_verdicts(data, len(items)).items()}


async def judge_pages(llm: LLM, pages: list[Page]) -> dict[Item, tuple[str, str]]:
    """All batches of all pages concurrently (the LLM semaphore bounds the calls)."""
    jobs = [judge_items(llm, page, batch) for page in pages for batch in batches(page.items)]
    verdicts: dict[Item, tuple[str, str]] = {}
    for part in await asyncio.gather(*jobs):
        verdicts.update(part)
    return verdicts


def load_pages(conn: psycopg.Connection, source: str | None = None) -> list[Page]:
    """Pages with verified claims of the judged fields or verified relations, with their items."""
    src = "AND p.source_id = %(source)s" if source else ""
    pages: dict[int, tuple[str, str]] = {}
    items: dict[int, list[Item]] = {}
    claims = conn.execute(
        f"""SELECT p.id, p.url, coalesce(p.title, ''), c.id, e.type, e.name, c.field, c.value, c.quote
            FROM claim c JOIN entity e ON e.id = c.entity_id JOIN page p ON p.id = c.page_id
            WHERE c.verified AND c.field = ANY(%(fields)s) {src} ORDER BY p.id, c.id""",
        {"fields": list(JUDGED_FIELDS), "source": source},
    ).fetchall()
    for page_id, url, title, cid, etype, name, field, value, quote in claims:
        pages[page_id] = (url, title)
        items.setdefault(page_id, []).append(
            Item("claim", cid, f'{etype} "{name}" — {field}: "{_one_line(value)}"', quote))
    relations = conn.execute(
        f"""SELECT p.id, p.url, coalesce(p.title, ''), r.id, f.type, f.name, r.rel, t.type, t.name, r.quote
            FROM relation r JOIN entity f ON f.id = r.from_id JOIN entity t ON t.id = r.to_id
            JOIN page p ON p.id = r.page_id
            WHERE r.verified {src} ORDER BY p.id, r.id""",
        {"source": source},
    ).fetchall()
    for page_id, url, title, rid, ftype, fname, rel, ttype, tname, quote in relations:
        pages[page_id] = (url, title)
        items.setdefault(page_id, []).append(
            Item("relation", rid, f'relation: {ftype} "{fname}" {rel} {ttype} "{tname}"', quote))
    return [Page(pid, *pages[pid], items[pid]) for pid in sorted(pages)]


def store_verdicts(conn: psycopg.Connection, pages: list[Page], verdicts: dict[Item, tuple[str, str]]) -> None:
    """Reset the judged rows of these pages to NULL, then write the new verdicts (missing → NULL)."""
    with conn.transaction():
        for table in ("claim", "relation"):
            ids = [item.row_id for page in pages for item in page.items if item.table == table]
            conn.execute(f"UPDATE {table} SET judge_verdict = NULL, judge_reason = NULL WHERE id = ANY(%s)", (ids,))
            rows = [(v, reason, item.row_id) for item, (v, reason) in verdicts.items() if item.table == table]
            with conn.cursor() as cur:
                cur.executemany(f"UPDATE {table} SET judge_verdict = %s, judge_reason = %s WHERE id = %s", rows)


def run_judge(conn: psycopg.Connection, llm: LLM, source: str | None = None) -> Counter:
    """Judge every page (of one source) and store the verdicts. Returns counts by (table, verdict)."""
    pages = load_pages(conn, source)
    verdicts = asyncio.run(judge_pages(llm, pages))
    store_verdicts(conn, pages, verdicts)
    counts = Counter((item.table, verdicts.get(item, ("not judged",))[0]) for page in pages for item in page.items)
    counts[("pages", "judged")] = len(pages)
    unjudged = sum(item not in verdicts for page in pages for item in page.items)
    if unjudged:
        log.warning("judge: %d of %d items not judged (failed calls are logged above)", unjudged,
                    sum(len(page.items) for page in pages))
    return counts
