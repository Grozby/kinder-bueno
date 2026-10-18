"""Eval judge [PoC] (plan 10.3): an LLM marks each top-10 result relevant or not, from its shown evidence only.

Same model family as the extractor, so it is biased (plan 3): a PoC precision signal, not ground truth.
"""

import asyncio
import logging
import re
from dataclasses import dataclass

from navigator.llm import LLM
from navigator.models import Result

log = logging.getLogger(__name__)

TIMEOUT = 90.0  # seconds per query; a failed or slow call leaves the query "not judged"
MAX_EVIDENCE = 8  # evidence rows per result, so ten results fit one prompt
MAX_QUOTE = 200

SYSTEM = """You judge results of an expert search in the Bern research ecosystem.
For each result, decide if this person or unit is a good match for the query.
Use ONLY the evidence listed. Do not use your own knowledge.
- relevant = true: the evidence shows work on the query topic or a close sub-topic.
- relevant = false: otherwise, or if the evidence is too thin to tell.
Return ONLY JSON: {"<entity_id>": {"relevant": true|false, "reason": "<one short sentence>"}, ...}
Use the number at the start of each result as the key, without the name."""


@dataclass(frozen=True)
class Verdict:
    relevant: bool
    reason: str


def format_results(results: list[Result]) -> str:
    """Name, type and shown evidence per result. No URLs or scores: the judge must not see the ranking."""
    blocks = []
    for r in results:
        rows = [f'  - {e.field}: {e.value} — "{e.quote[:MAX_QUOTE]}"' for e in r.evidence[:MAX_EVIDENCE]]
        blocks.append("\n".join([f"{r.entity_id} {r.name} ({r.type})", *rows]))
    return "\n".join(blocks)


def parse_verdicts(data: dict, entity_ids: set[int]) -> dict[int, Verdict]:
    """Verdicts for known entity ids with a boolean `relevant`; anything else is dropped.
    Keys may carry the name after the id ("4 ARTORG Center"): Apertus sometimes copies the whole result line."""
    verdicts = {}
    for key, value in data.items():
        m = re.match(r"\s*(\d+)\b", str(key))
        if not m:
            continue
        entity_id = int(m.group(1))
        if entity_id in entity_ids and isinstance(value, dict) and isinstance(value.get("relevant"), bool):
            verdicts[entity_id] = Verdict(value["relevant"], str(value.get("reason") or ""))
    return verdicts


async def judge_query(llm: LLM, query: str, results: list[Result], timeout: float = TIMEOUT) -> dict[int, Verdict] | None:
    """Verdicts per entity id, or None if the query could not be judged (no results, error, timeout, no usable verdict)."""
    if not results:
        return None
    user = f"Query: {query}\nResults:\n{format_results(results)}"
    try:
        data = await asyncio.wait_for(llm.chat_json(SYSTEM, user, max_tokens=1500), timeout)
    except Exception as e:  # LLM, network or timeout: the query is left out of the mean
        log.warning("eval judge failed for %r: %s", query, e or type(e).__name__)
        return None
    return parse_verdicts(data, {r.entity_id for r in results}) or None


async def judge_all(llm: LLM, runs: dict[str, list[Result]]) -> dict[str, dict[int, Verdict] | None]:
    """All queries concurrently on one event loop (the LLM semaphore bounds the calls)."""
    verdicts = await asyncio.gather(*(judge_query(llm, q, results) for q, results in runs.items()))
    return dict(zip(runs, verdicts))


def precision(results: list[Result], verdicts: dict[int, Verdict] | None) -> float | None:
    """Share of judged results marked relevant; None if the query was not judged."""
    judged = [verdicts[r.entity_id].relevant for r in results if verdicts and r.entity_id in verdicts]
    return sum(judged) / len(judged) if judged else None


def log_rows(runs: dict[str, list[Result]], verdicts: dict[str, dict[int, Verdict] | None]) -> list[dict]:
    """One row per judged result, for eval/judge_log.jsonl (spot checks, plan 16)."""
    return [
        {"query": q, "rank": i, "entity_id": r.entity_id, "name": r.name, "type": r.type,
         "relevant": v.relevant, "reason": v.reason}
        for q, results in runs.items()
        for i, r in enumerate(results, start=1)
        if (v := (verdicts.get(q) or {}).get(r.entity_id))
    ]
