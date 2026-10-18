"""Entity ranking: linking and cap as unit tests, the full ranker on the fixture graph (tests/conftest.py)."""

import numpy as np
import pytest
from conftest import onehot

from navigator.rank import (
    _is_real_model,
    _topic_vec_of,
    _units,
    entity_scores,
    fairness_cap,
    home_folder,
    idf,
    inherit,
    rank_entities,
    section_scores,
    topic_scores,
)
from navigator.search import ChunkHit


def _hit(chunk_id: int, page_id: int, text: str, score: float) -> ChunkHit:
    return ChunkHit(chunk_id, page_id, f"https://p{page_id}", text, score, None)


def test_quote_in_chunk_gets_full_weight_same_page_less():
    hits = [_hit(1, 10, "Anna Muster works on  Surgical robotics.", 1.0)]
    claims = [(1, 10, "surgical robotics"), (2, 10, "cardiac imaging"), (3, 99, "surgical robotics")]
    assert entity_scores(hits, claims) == {1: 1.0, 2: 0.25}


def test_entity_score_is_its_best_chunk():
    # a long page with many matching chunks must not beat a one-chunk lab page (#29)
    hits = [_hit(i, 10, "quote", s) for i, s in enumerate([0.4, 0.3, 0.2, 0.1], start=1)]
    assert entity_scores(hits, [(7, 10, "quote")]) == {7: pytest.approx(0.4)}


def test_chunk_naming_many_entities_counts_less_for_each():
    hits = [_hit(1, 10, "anna ben carl dora", 1.0)]
    claims = [(1, 10, "anna"), (2, 10, "ben"), (3, 10, "carl"), (4, 10, "dora")]
    assert entity_scores(hits, claims) == {e: pytest.approx(0.5) for e in (1, 2, 3, 4)}  # 1 / sqrt(4)


def test_entity_weight_scales_its_score():
    hits = [_hit(1, 10, "quote", 1.0)]
    assert entity_scores(hits, [(7, 10, "quote")], weight={7: 0.3}) == {7: pytest.approx(0.3)}


def test_idf_is_one_on_a_single_page_and_small_on_most_pages():
    assert idf(1, 100) == pytest.approx(1.0)
    assert idf(50, 100) < 0.3 < idf(5, 100)


def test_members_inherit_their_best_units_score():
    scores = {10: 1.0, 11: 0.4, 1: 0.1}  # units 10, 11; person 1 has its own score
    out = inherit(scores, [(1, 10), (1, 11), (2, 11), (3, 99)], share=0.5)
    assert out == {10: 1.0, 11: 0.4, 1: pytest.approx(0.6), 2: pytest.approx(0.2)}  # 3: unit 99 did not match


def test_home_folder_is_the_folder_above_the_member_page():
    assert home_folder("https://a.ch/research/aihn/group_members/index_eng.html") == "https://a.ch/research/aihn/"
    assert home_folder("https://www.dcberne.com/en/team/") == "https://www.dcberne.com/en/"


def test_section_scores_credit_the_deepest_owner():
    def hit(url: str, score: float) -> ChunkHit:
        return ChunkHit(1, 1, url, "text", score, None)

    homes = [(1, "https://a.ch/research/aihn/"), (2, "https://a.ch/"), (3, "https://a.ch/research/nrg/")]
    hits = [hit("https://a.ch/research/aihn/diabetes/index.html", 0.4), hit("https://a.ch/research/aihn/x", 0.1),
            hit("https://a.ch/about.html", 0.2)]
    # the lab, not the whole site, owns its pages; the site owns the rest; nrg has no hit
    assert section_scores(hits, homes, weight=0.5) == {1: pytest.approx(0.2), 2: pytest.approx(0.1)}


def test_topic_score_is_the_best_matching_topic():
    vecs = {"robotics": np.array([1.0, 0.0]), "nutrition": np.array([0.0, 1.0]), "imaging": np.array([0.6, 0.8])}
    claims = [(1, "robotics"), (1, "nutrition"), (2, "imaging")]
    sims = topic_scores(claims, [np.array([1.0, 0.0])], vecs.__getitem__)
    assert sims == {1: pytest.approx(1.0), 2: pytest.approx(0.6)}


def test_topic_vectors_are_cached_per_embedding_function():
    calls = []

    def fake(text):
        calls.append(text)
        return np.array([1.0, 0.0])

    vec_of = _topic_vec_of(fake, ["a", "b", "a"])
    assert vec_of("a").tolist() == [1.0, 0.0] and calls == ["a", "b"]
    _topic_vec_of(fake, ["a", "b", "c"])
    assert calls == ["a", "b", "c"]  # only the new value is embedded
    other = _topic_vec_of(lambda text: np.array([0.0, 1.0]), ["a"])
    assert other("a").tolist() == [0.0, 1.0]  # another function never sees fake's vectors


def test_the_api_embed_function_counts_as_the_real_model():
    from navigator import embed

    assert _is_real_model(None) and _is_real_model(embed.embed_query)
    assert not _is_real_model(lambda text: text)


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


def test_member_found_through_the_unit_only(test_conn, graph):
    # Bob's own claims are on page 3; "insulin" only matches the lab page. He is listed in the lab: he inherits.
    test_conn.execute(
        "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) VALUES (%s, 'listed_in', %s, 'q', %s, true)",
        (graph["bob"], graph["lab"], graph["p3"]),
    )
    ids = [e for e, _ in rank_entities(test_conn, "insulin", embed=lambda q: onehot({2: 1.0})).ranked]
    assert graph["bob"] in ids and graph["lab"] in ids


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


def test_unit_found_through_its_own_topics(test_conn, graph, monkeypatch):
    # The query matches Bob's page (p3), where the lab has no claim; the lab's expertise claim matches the query.
    test_conn.execute(
        "INSERT INTO claim (entity_id, field, value, quote, page_id, verified) "
        "VALUES (%s, 'expertise', 'zebrafish genetics', 'q', %s, true)",
        (graph["lab"], graph["p2"]),
    )

    def embed(text: str):
        if text == "zebrafish genetics":
            return onehot({3: 0.6, 7: 0.8})  # the query
        return onehot({7: 1.0}) if "zebrafish" in text else onehot({1: 1.0})  # topic values

    def ranked() -> list[int]:
        return [e for e, _ in rank_entities(test_conn, "zebrafish genetics", embed=embed).ranked]

    assert ranked()[0] == graph["lab"]
    monkeypatch.setattr("navigator.rank.TOPIC_WEIGHT", 0.0)
    assert ranked()[-1] == graph["lab"]  # without topics it only has a weak page link


def test_each_query_string_is_embedded_once(test_conn, graph):
    calls = []

    def embed(text: str):
        calls.append(text)
        return onehot({3: 0.8, 1: 0.6})

    rank_entities(test_conn, "glucose", extra_terms=["CGM"], embed=embed)
    assert calls.count("glucose") == 1 and calls.count("glucose, CGM") == 1  # chunk search and topic match share
