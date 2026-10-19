"""Claim judge tests (plan 7.8): parsing and failures with a fake LLM; storage on the test graph (needs Postgres)."""

import asyncio

from navigator.ingest.judge import (
    MAX_ITEMS,
    Item,
    Page,
    batches,
    format_items,
    judge_items,
    judge_pages,
    load_pages,
    parse_verdicts,
    store_verdicts,
)
from navigator.results import build_results

GLUCOSE = Item("claim", 11, 'person "Anna Muster" — expertise: "glucose sensors"', "Anna works on\nglucose sensors.")
LISTED = Item("relation", 21, 'relation: person "Anna Muster" listed_in unit "Diabetes Lab"', "Anna Muster, PhD")
PAGE = Page(1, "https://x.example/team", "Team", [GLUCOSE, LISTED])


class FakeLLM:
    def __init__(self, answer=None, error: Exception | None = None):
        self.answer, self.error = answer, error
        self.prompts: list[str] = []

    async def chat_json(self, system: str, user: str, max_tokens: int = 4096, timeout: float | None = None) -> dict:
        self.prompts.append(user)
        if self.error:
            raise self.error
        return self.answer


def test_format_items_numbers_items_on_one_line_each():
    assert format_items(PAGE, PAGE.items) == (
        "Page URL: https://x.example/team\nPage title: Team\n\nItems:\n"
        '[1] person "Anna Muster" — expertise: "glucose sensors"\n'
        '    quote: "Anna works on glucose sensors."\n'
        '[2] relation: person "Anna Muster" listed_in unit "Diabetes Lab"\n'
        '    quote: "Anna Muster, PhD"'
    )


def test_parse_verdicts_keeps_valid_rows_only():
    data = {"verdicts": [
        {"id": 1, "verdict": "supported", "reason": "states it"},
        {"id": "[2]", "verdict": "Partial", "reason": "broader"},  # "[2]" and capitals are accepted
        {"id": 3, "verdict": "supported"},                         # no item 3
        {"id": 2, "verdict": "maybe"},                             # unknown verdict (and a 2nd row for 2)
        "nonsense",
    ]}
    assert parse_verdicts(data, 2) == {1: ("supported", "states it"), 2: ("partial", "broader")}
    assert parse_verdicts({"verdicts": "x"}, 2) == {}
    assert parse_verdicts({}, 2) == {}


def test_judge_items_maps_numbers_to_items_and_missing_stays_null():
    llm = FakeLLM({"verdicts": [{"id": 2, "verdict": "supported", "reason": "her entry"}]})
    assert asyncio.run(judge_items(llm, PAGE, PAGE.items)) == {LISTED: ("supported", "her entry")}


def test_failed_call_gives_no_verdicts():
    assert asyncio.run(judge_items(FakeLLM(error=ConnectionError("down")), PAGE, PAGE.items)) == {}


def test_big_pages_are_split_into_batches():
    items = [Item("claim", i, f"line {i}", "q") for i in range(MAX_ITEMS + 3)]
    assert [len(b) for b in batches(items)] == [MAX_ITEMS, 3]
    llm = FakeLLM({"verdicts": [{"id": 1, "verdict": "supported", "reason": "r"}]})
    verdicts = asyncio.run(judge_pages(llm, [Page(1, "u", "t", items)]))
    assert len(llm.prompts) == 2
    assert set(verdicts) == {items[0], items[MAX_ITEMS]}  # item 1 of each batch


def test_load_pages_selects_verified_judged_fields_and_relations(test_conn, graph):
    pages = {p.url: p for p in load_pages(test_conn)}
    claim_ids = {i.row_id for p in pages.values() for i in p.items if i.table == "claim"}
    assert claim_ids == {graph[k] for k in ("lab_expertise", "alice_glucose", "alice_robotics", "alice_diabetes", "bob_glucose")}
    # no name/role/email/phone, no unverified claims (Carol), no unverified relation
    lines = [i.line for p in pages.values() for i in p.items if i.table == "relation"]
    assert len(lines) == 6
    assert 'relation: unit "Diabetes Lab" part_of unit "ARTORG Center"' in lines
    assert [p.url for p in load_pages(test_conn, "dcb")] == ["https://dcb.example/bob"]


def test_store_verdicts_resets_and_writes_and_hides_unsupported(test_conn, graph):
    pages = load_pages(test_conn)
    items = {i.row_id: i for p in pages for i in p.items if i.table == "claim"}
    verdicts = {
        items[graph["bob_glucose"]]: ("unsupported", "the quote is about Alice"),
        items[graph["lab_expertise"]]: ("partial", "broader"),
    }
    store_verdicts(test_conn, pages, verdicts)
    rows = dict(test_conn.execute(
        "SELECT id, judge_verdict FROM claim WHERE id = ANY(%s)",
        ([graph[k] for k in ("bob_glucose", "lab_expertise", "alice_glucose", "alice_robotics", "bob_role")],),
    ).fetchall())
    assert rows[graph["bob_glucose"]] == "unsupported"
    assert rows[graph["lab_expertise"]] == "partial"
    assert rows[graph["alice_glucose"]] is None   # judged before, missing now → NULL
    assert rows[graph["alice_robotics"]] is None  # was unsupported, missing now → NULL (shown again)
    assert rows[graph["bob_role"]] is None        # never judged
    # "unsupported" claims are not shown (plan 7.1), so Bob's card loses its expertise.
    bob = build_results(test_conn, [(graph["bob"], 1.0)])[0]
    assert "glucose sensors" not in bob.expertise
    assert bob.role == ["Postdoc"]
