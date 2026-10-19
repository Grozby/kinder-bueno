"""RRF unit tests, plus integration tests that need Postgres (skipped otherwise). No model is loaded."""

import numpy as np
import psycopg
import pytest

from navigator import chunks_db
from navigator.search import (
    ChunkHit,
    cap_per_page,
    keyword_search,
    query_words,
    rrf,
    search_chunks,
)

DIM = 1024


def test_rrf_sums_reciprocal_ranks():
    fused = dict(rrf([[1, 2, 3], [3, 1]], k=60))
    assert fused[1] == pytest.approx(1 / 61 + 1 / 62)
    assert fused[2] == pytest.approx(1 / 62)
    assert fused[3] == pytest.approx(1 / 63 + 1 / 61)


def test_rrf_orders_best_first_and_breaks_ties_by_id():
    assert [i for i, _ in rrf([[5, 7], [7, 5]])] == [5, 7]
    assert [i for i, _ in rrf([[1, 2], [2]])] == [2, 1]
    assert rrf([]) == []


def _hit(chunk_id: int, page_id: int) -> ChunkHit:
    return ChunkHit(chunk_id, page_id, f"https://p{page_id}", "", 1.0 / chunk_id, None)


def test_cap_per_page_keeps_the_best_hits_of_each_page_in_order():
    hits = [_hit(1, 10), _hit(2, 10), _hit(3, 20), _hit(4, 10), _hit(5, 20), _hit(6, 30)]
    assert [h.chunk_id for h in cap_per_page(hits, 2)] == [1, 2, 3, 5, 6]
    assert [h.chunk_id for h in cap_per_page(hits, 1)] == [1, 3, 6]
    assert cap_per_page([], 2) == []


def _onehot(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture
def conn(test_database_url):
    """A connection to the run's test database (tests/conftest.py) whose test data is rolled back at the end."""
    with chunks_db.connect(test_database_url) as connection, connection.transaction() as tx:
        yield connection
        raise psycopg.Rollback(tx)


@pytest.fixture
def test_source(conn):
    conn.execute("INSERT INTO source (id, name) VALUES ('zztest', 'Test') ON CONFLICT DO NOTHING")
    page_id = conn.execute(
        "INSERT INTO page (source_id, url, title, text) VALUES ('zztest', 'https://zz.test/p', 'T', 'x') "
        "RETURNING id"
    ).fetchone()[0]
    chunks_db.replace_chunks(
        conn,
        "zztest",
        [
            (page_id, 0, "T\n\nquuxglucose sensors for zzwidgets", _onehot(3)),
            (page_id, 1, "T\n\nsomething about zzwidgets only", _onehot(5)),
        ],
    )
    return page_id


def test_replace_chunks_replaces_old_ones(conn, test_source):
    chunks_db.replace_chunks(conn, "zztest", [(test_source, 0, "T\n\nnew", _onehot(7))])
    rows = conn.execute("SELECT text FROM chunk WHERE page_id = %s", (test_source,)).fetchall()
    assert rows == [("T\n\nnew",)]


def test_query_words_drops_stopwords(conn):
    assert sorted(query_words(conn, "Who works on the heart valves?")) == ["heart", "valves", "works"]
    assert sorted(query_words(conn, "Forschung mit der Herzklappe und dem Herz")) == ["forschung", "herz", "herzklappe"]
    assert query_words(conn, "the") == ["the"]  # only stopwords: keep them
    assert query_words(conn, "  ") == []


def test_keyword_search_matches_query_words_in_any_order(conn, test_source):
    # Regression for #2: a multi-word query used to be one exact phrase, so this found nothing.
    ids = keyword_search(conn, "zzwidgets quuxglucose nomatchzz")
    assert len(ids) == 2
    first_text = conn.execute("SELECT text FROM chunk WHERE id = %s", (ids[0],)).fetchone()[0]
    assert "quuxglucose" in first_text  # matches more of the words, so it ranks first
    assert keyword_search(conn, "the nomatchzz") == []  # "the" would match almost every chunk
    assert keyword_search(conn, "") == []


def test_keyword_search_keeps_extra_terms_as_phrases(conn, test_source):
    assert len(keyword_search(conn, "nomatchzz", ["quuxglucose sensors"])) == 1
    assert keyword_search(conn, "nomatchzz", ["sensors quuxglucose"]) == []  # phrase order matters
    assert len(keyword_search(conn, "nomatchzz", ["nomatch2zz", "zzwidgets"])) == 2


def test_search_chunks_fuses_keyword_and_semantic(conn, test_source):
    hits = search_chunks(conn, "zzwidgets", ["quuxglucose"], embed=lambda q: _onehot(3))
    top = hits[0]
    assert top.url == "https://zz.test/p"
    assert top.text.startswith("T\n\nquuxglucose")
    assert top.similarity == pytest.approx(1.0)
    assert top.score > hits[1].score


def test_search_chunks_caps_chunks_per_page(conn, test_source):
    # Regression for #3: one long page used to fill the top of the list.
    def fake_embed(q):
        return _onehot(3)

    capped = search_chunks(conn, "zzwidgets", embed=fake_embed, max_per_page=1)
    assert [h.page_id for h in capped].count(test_source) == 1
    uncapped = search_chunks(conn, "zzwidgets", embed=fake_embed, max_per_page=None)
    assert [h.page_id for h in uncapped].count(test_source) == 2
