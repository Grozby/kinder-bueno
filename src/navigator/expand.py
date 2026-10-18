"""Query expansion with Apertus (plan 8.1): English and German search terms for a query."""

import asyncio
import logging
import re
from dataclasses import dataclass, field

from navigator.llm import LLM

log = logging.getLogger(__name__)

MAX_TERMS = 8  # per language
TIMEOUT = 10.0  # seconds; expansion is on the query path, so a slow gateway must not block search

SYSTEM = """You help search a database of research experts in Bern, Switzerland.
Give search terms for the user query: synonyms, technical terms, lay terms,
abbreviations, and German translations. Max 8 English and 8 German terms.
Return ONLY JSON: {"en": ["..."], "de": ["..."]}"""


@dataclass(frozen=True)
class Expansion:
    en: list[str] = field(default_factory=list)
    de: list[str] = field(default_factory=list)

    @property
    def terms(self) -> list[str]:
        """English first: search_chunks embeds the query with the first 4 terms (plan 8.3). No duplicates
        (abbreviations like "CGM" often come back in both languages)."""
        terms: dict[str, str] = {}
        for term in [*self.en, *self.de]:
            terms.setdefault(term.lower(), term)
        return list(terms.values())


_cache: dict[str, Expansion] = {}


def _split_abbreviation(term: str) -> list[str]:
    """ "continuous glucose monitoring (CGM)" -> ["continuous glucose monitoring", "CGM"]."""
    m = re.fullmatch(r"(.+?)\s*\(([^()]+)\)", term)
    return [m.group(1), m.group(2)] if m else [term]


def _clean_terms(values: object, query: str) -> list[str]:
    """Strings only, trimmed, abbreviations split off, no duplicates, not the query itself, at most MAX_TERMS."""
    if not isinstance(values, list):
        return []
    seen = {" ".join(query.lower().split())}
    terms = []
    for value in values:
        if not isinstance(value, str):
            continue
        for term in _split_abbreviation(" ".join(value.split())):
            key = term.lower()
            if term and key not in seen:
                seen.add(key)
                terms.append(term)
    return terms[:MAX_TERMS]


def parse_expansion(data: dict, query: str) -> Expansion:
    return Expansion(en=_clean_terms(data.get("en"), query), de=_clean_terms(data.get("de"), query))


async def expand_query(llm: LLM, query: str, timeout: float = TIMEOUT) -> Expansion:
    """Search terms for `query`, cached per process. Any failure gives an empty expansion (search the query only)."""
    key = " ".join(query.lower().split())
    if not key:
        return Expansion()
    if key in _cache:
        return _cache[key]
    try:
        data = await asyncio.wait_for(llm.chat_json(SYSTEM, f"Query: {query}", max_tokens=400), timeout)
    except Exception as e:  # LLM, network or timeout: never fail the search because of expansion
        log.warning("query expansion failed for %r: %s", query, e or type(e).__name__)
        return Expansion()
    expansion = parse_expansion(data, query)
    _cache[key] = expansion
    return expansion
