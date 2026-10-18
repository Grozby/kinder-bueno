"""RRF unit tests, plus integration tests that need Postgres (skipped otherwise). No model is loaded."""

import numpy as np
import psycopg
import pytest

from navigator import chunks_db
from navigator.search import keyword_search, query_words, rrf, search_chunks
from navigator.settings import get_settings

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


def _onehot(i: int) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    v[i] = 1.0
    return v


@pytest.fixture
def conn():
    """A connection whose test data is rolled back at the end."""
    try:
        connection = chunks_db.connect(get_settings().database_url)
    except psycopg.OperationalError:
        pytest.skip("Postgres not running")
    with connection:
        try:
            with connection.transaction() as tx:
                yield connection
                raise psycopg.Rollback(tx)
        except psycopg.errors.UndefinedTable:
            pytest.skip("schema not applied")


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
