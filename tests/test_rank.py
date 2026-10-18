"""Entity ranking: linking and cap as unit tests, the full ranker on the fixture graph (tests/conftest.py)."""

import pytest

from conftest import onehot
from navigator.rank import _units, entity_scores, fairness_cap, rank_entities
from navigator.search import ChunkHit


def _hit(chunk_id: int, page_id: int, text: str, score: float) -> ChunkHit:
    return ChunkHit(chunk_id, page_id, f"https://p{page_id}", text, score, None)


def test_quote_in_chunk_gets_full_weight_same_page_half():
    hits = [_hit(1, 10, "Anna Muster works on  Surgical robotics.", 1.0)]
    claims = [(1, 10, "surgical robotics"), (2, 10, "cardiac imaging"), (3, 99, "surgical robotics")]
    assert entity_scores(hits, claims) == {1: 1.0, 2: 0.5}


def test_entity_score_is_sum_of_best_three_chunks():
    hits = [_hit(i, 10, "quote", s) for i, s in enumerate([0.4, 0.3, 0.2, 0.1], start=1)]
    assert entity_scores(hits, [(7, 10, "quote")]) == {7: pytest.approx(0.9)}


def test_fairness_cap_allows_three_per_unit():
    ranked = [(e, 1.0 - e / 100) for e in range(1, 8)]
    unit_of = {1: 50, 2: 50, 3: 50, 4: 50, 5: 60}  # 6 and 7 have no unit
    assert [e for e, _ in fairness_cap(ranked, unit_of)] == [1, 2, 3, 5, 6, 7]
    assert [e for e, _ in fairness_cap(ranked, unit_of, limit=4)] == [1, 2, 3, 5]


def test_rank_orders_by_relevance(test_conn, graph):
    ranking = rank_entities(test_conn, "glucose", embed=lambda q: onehot({3: 0.8, 1: 0.6}))
    ids = [e for e, _ in ranking.ranked]
    assert ranking.no_result is False
    assert set(ids[:2]) == {graph["bob"], graph["alice"]}
    assert graph["carol"] not in ids


def test_no_reliable_result_when_low_similarity_and_no_keyword_hit(test_conn, graph):
    ranking = rank_entities(test_conn, "zebrafish", embed=lambda q: onehot({10: 1.0}))
    assert (ranking.ranked, ranking.no_result) == ([], True)


def test_projects_only_when_asked(test_conn, graph):
    embed = lambda q: onehot({2: 1.0})  # noqa: E731
    default = [e for e, _ in rank_entities(test_conn, "pancreas", embed=embed).ranked]
    assert graph["pancreas"] not in default
    projects = rank_entities(test_conn, "pancreas", types=["project"], embed=embed).ranked
    assert [e for e, _ in projects] == [graph["pancreas"]]


def test_unit_from_member_of_first_then_listed_in(test_conn, graph):
    def listed_in(person: str, unit: str) -> None:
        test_conn.execute(
            "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) VALUES (%s, 'listed_in', %s, 'q', %s, true)",
            (graph[person], graph[unit], graph["p1"]),
        )

    listed_in("alice", "center")  # Alice is member_of the lab: member_of wins
    test_conn.execute("DELETE FROM relation WHERE from_id = %s", (graph["bob"],))
    listed_in("bob", "lab")  # Bob has only listed_in
    assert _units(test_conn, [graph["alice"], graph["bob"]]) == {graph["alice"]: graph["lab"], graph["bob"]: graph["lab"]}
