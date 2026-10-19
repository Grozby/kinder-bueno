"""Quote verification: a fact is only kept if its quote is really on the page (PLAN 7.6).

Matching happens on normalised text, but the stored quote is always mapped back to the
exact original page text, so the UI shows a literal slice of the source page.
"""

import re
import unicodedata
from dataclasses import dataclass

from rapidfuzz import fuzz

FUZZY_MIN_SCORE = 95.0
VALUE_IN_QUOTE_FIELDS = {"name", "role", "email", "phone"}
TOPIC_FIELDS = {"expertise", "description"}  # the quote must be a sentence or name the topic (#149)
MIN_SENTENCE_WORDS = 8
MAX_PAIR_DISTANCE = 200  # max characters between a person's name and their role/email/phone

_CHAR_MAP = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ",
})


def norm(text: str) -> str:
    return normalise_with_map(text)[0]


def normalise_with_map(text: str) -> tuple[str, list[int]]:
    """NFKC, ASCII quotes and dashes, lowercase, whitespace collapsed to one space.

    Returns the normalised string and, for each of its characters, the index of the
    original character it came from.
    """
    out: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        for c in unicodedata.normalize("NFKC", ch).translate(_CHAR_MAP).lower():
            if c.isspace():
                if not out or out[-1] == " ":
                    continue
                c = " "
            out.append(c)
            origin.append(i)
    while out and out[-1] == " ":
        out.pop()
        origin.pop()
    if out and out[0] == " ":
        out.pop(0)
        origin.pop(0)
    return "".join(out), origin


@dataclass
class QuoteMatch:
    ok: bool
    quote: str            # exact page text when ok, else the input quote
    fuzzy: bool = False
    reason: str | None = None
    rebuilt: bool = False  # quote built from the page, not copied by the model


def _occurrences(haystack: str, needle: str) -> list[int]:
    starts, i = [], haystack.find(needle)
    while i >= 0:
        starts.append(i)
        i = haystack.find(needle, i + 1)
    return starts


class PageText:
    """A page's text, normalised once and reused for every claim on the page."""

    def __init__(self, text: str):
        self.text = text
        self.normed, self.origin = normalise_with_map(text)

    def _original_span(self, start: int, end: int) -> str:
        return self.text[self.origin[start]: self.origin[end - 1] + 1]

    def contains(self, value: str) -> bool:
        needle = norm(value)
        return bool(needle) and needle in self.normed

    def find_quote(self, quote: str) -> QuoteMatch:
        needle = norm(quote)
        if not needle:
            return QuoteMatch(False, quote, reason="empty quote")
        start = self.normed.find(needle)
        if start >= 0:
            return QuoteMatch(True, self._original_span(start, start + len(needle)))
        if len(needle) < 10:  # too short for a meaningful fuzzy match
            return QuoteMatch(False, quote, reason="quote not on page")
        best = fuzz.partial_ratio_alignment(needle, self.normed, score_cutoff=FUZZY_MIN_SCORE)
        if best is None:
            return QuoteMatch(False, quote, reason="quote not on page")
        start, end = self._refine_window(needle, best.dest_start, best.dest_end)
        return QuoteMatch(True, self._original_span(start, end), fuzzy=True)

    def rebuild_quote(self, entity_name: str, field: str, value: str) -> QuoteMatch | None:
        """For short facts (name, role, email, phone) the quote can be taken from the page itself:
        the value's text for a name, else the shortest page span holding the entity name and the
        value close together. The model's copy is often reordered ("Name\nRole" for "Role\nName")."""
        v = norm(value)
        if not v:
            return None
        if field == "name":
            starts = _occurrences(self.normed, v)
            return QuoteMatch(True, self._original_span(starts[0], starts[0] + len(v)), rebuilt=True) if starts else None
        name = norm(entity_name)
        best = None
        for n in _occurrences(self.normed, name):
            for s in _occurrences(self.normed, v):
                start, end = min(n, s), max(n + len(name), s + len(v))
                gap = end - start - len(name) - len(v)
                if gap <= MAX_PAIR_DISTANCE and (best is None or end - start < best[1] - best[0]):
                    best = (start, end)
        return QuoteMatch(True, self._original_span(*best), rebuilt=True) if best else None

    def _refine_window(self, needle: str, start: int, end: int) -> tuple[int, int]:
        """The alignment window is as long as the quote. When the page has a few extra
        characters (a dash the model dropped), it cuts off the edges. Move both edges a
        little and keep the window that matches the whole quote best."""
        slack = max(3, len(needle) // 10)
        best = (fuzz.ratio(needle, self.normed[start:end]), start, end)
        for s in range(max(0, start - slack), start + slack + 1):
            for e in range(max(s + 1, end - slack), min(len(self.normed), end + slack) + 1):
                score = fuzz.ratio(needle, self.normed[s:e])
                if score > best[0]:
                    best = (score, s, e)
        return best[1], best[2]


def names_topic(value: str, quote: str) -> bool:
    """A content word of the value (its first 5 letters, so "valves" names "valve") is in the quote, or the value
    has no content words to look for ("AI")."""
    words = [w[:5] for w in re.findall(r"[^\W\d_]{4,}", norm(value))]
    q = norm(quote)
    return not words or any(w in q for w in words)


def is_sentence(quote: str) -> bool:
    """Prose, not a heading or a label: long enough, or with sentence punctuation."""
    return len(re.findall(r"\w+", quote)) >= MIN_SENTENCE_WORDS or bool(re.search(r"[.;:!?](\s|$)", quote.strip()))


def verify_claim(page: PageText, entity_name: str, field: str, value: str, quote: str) -> QuoteMatch:
    """Checks 1-3 of PLAN 7.6. On success, `quote` is replaced by the exact page text.
    A topic (expertise, description) quoted only by a heading or label that does not name it is rejected: on pages
    without research text the model copies the prompt's example topics and quotes "Team" or the lab name (#149)."""
    if not page.contains(entity_name):
        return QuoteMatch(False, quote, reason="entity name not on page")
    match = page.find_quote(quote)
    if field in TOPIC_FIELDS:
        if match.ok and not is_sentence(match.quote) and not names_topic(value, match.quote):
            return QuoteMatch(False, match.quote, reason="topic not named in a heading-only quote")
        return match
    if field not in VALUE_IN_QUOTE_FIELDS:
        return match
    if match.ok and norm(value) in norm(match.quote):
        return match
    rebuilt = page.rebuild_quote(entity_name, field, value)
    if rebuilt:
        return rebuilt
    if not match.ok:
        return match
    return QuoteMatch(False, quote, reason=f"{field} value not in quote")


def verify_relation(page: PageText, from_name: str, to_name: str, quote: str) -> QuoteMatch:
    match = page.find_quote(quote)
    if not match.ok:
        return match
    if not (page.contains(from_name) and page.contains(to_name)):
        return QuoteMatch(False, quote, reason="entity name not on page")
    return match
