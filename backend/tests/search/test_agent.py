"""Chat agent (plan 8.10, #97) on the fixture graph (tests/conftest.py), with scripted models instead of Apertus.
Needs Postgres."""

import pytest
import test_api
from fake_chat import Scripted
from langchain_core.messages import ToolMessage
from test_api import fake_embed

from navigator.models import ChatFilters, SearchResponse
from navigator.search import agent
from navigator.search.agent import Agent, Previous, check_reply, describe, template, text_tool_call
from navigator.search.rank import rank_entities
from navigator.search.results import build_results


def search_fn(conn):
    def run(q: str, f: ChatFilters) -> SearchResponse:
        ranked = rank_entities(conn, q, sources=[f.source] if f.source else [], types=[f.type] if f.type else [],
                               embed=fake_embed).ranked
        results = build_results(conn, ranked)
        return SearchResponse(results=results, expansion=None, no_result=not results)
    return run


def previous_of(conn, query: str, filters: ChatFilters | None = None) -> Previous:
    filters = filters or ChatFilters()
    found = search_fn(conn)(query, filters)
    return Previous(query=query, filters=filters, results=found.results, message=query, reply="Showing results.")


def names(turn_or_results) -> list[str]:
    results = getattr(turn_or_results, "results", turn_or_results)
    return [r.name for r in results]


def test_search_tool(test_conn, graph):
    model = Scripted({"name": "search", "args": {"query": "glucose"}}, "")
    turn = Agent(test_conn, model, search_fn(test_conn)).run("find glucose people", Previous())
    assert set(names(turn)[:2]) == {"Alice Muster", "Bob Beispiel"}
    assert turn.query == "glucose"
    assert turn.reply == f"Showing {len(turn.results)} results for 'glucose'."  # empty model reply: template
    assert turn.tools == ['search({"query": "glucose"})']


def test_set_filters_reruns_the_last_query(test_conn, graph):
    prev = previous_of(test_conn, "glucose")
    model = Scripted({"name": "set_filters", "args": {"source": "dcb"}}, "")
    turn = Agent(test_conn, model, search_fn(test_conn)).run("only DCB", prev)
    assert names(turn) == ["Bob Beispiel"]
    assert turn.filters == ChatFilters(source="dcb") and turn.query == "glucose"
    assert turn.reply.endswith("(source: dcb).")

    model = Scripted({"name": "set_filters", "args": {"source": "all"}}, "")
    again = Agent(test_conn, model, search_fn(test_conn)).run("all sources again", Previous(
        query="glucose", filters=turn.filters, results=turn.results))
    assert again.filters == ChatFilters() and "Alice Muster" in names(again)


def test_more_like_uses_the_topics_and_leaves_the_result_out(test_conn, graph):
    prev = previous_of(test_conn, "glucose")
    n = names(prev.results).index("Bob Beispiel") + 1
    model = Scripted({"name": "more_like", "args": {"result_number": n}}, "")
    turn = Agent(test_conn, model, search_fn(test_conn)).run(f"more like #{n}", prev)
    assert turn.query == "glucose sensors"  # Bob's shown expertise
    assert "Bob Beispiel" not in names(turn) and "Alice Muster" in names(turn)
    assert turn.reply == f"Showing {len(turn.results)} results similar to #{n} Bob Beispiel."


def test_related_walks_shown_relations_both_ways(test_conn, graph):
    prev = previous_of(test_conn, "insulin", ChatFilters(type="unit"))
    n = names(prev.results).index("Diabetes Lab") + 1
    model = Scripted({"name": "related", "args": {"result_number": n}}, "")
    turn = Agent(test_conn, model, search_fn(test_conn)).run(f"who works with #{n}?", Previous(
        query=prev.query, results=prev.results))
    # part_of → ARTORG Center, provides → Cleanroom, member_of ← Alice; Bob's member_of is judged unsupported
    assert names(turn) == ["ARTORG Center", "Cleanroom", "Alice Muster"]
    assert turn.reply == f"Showing 3 results linked to #{n} Diabetes Lab."

    people = Agent(test_conn, Scripted({"name": "related", "args": {"result_number": n}}, ""),
                   search_fn(test_conn)).run("who works there?", Previous(
                       query=prev.query, filters=ChatFilters(type="person"), results=prev.results))
    assert names(people) == ["Alice Muster"]  # the type filter applies to related results too

    members = Agent(test_conn, Scripted({"name": "related", "args": {"result_number": n, "rel": "provides"}}, ""),
                    search_fn(test_conn)).run("what does it run?", Previous(query=prev.query, results=prev.results))
    assert names(members) == ["Cleanroom"]

    invented = Agent(test_conn, Scripted({"name": "related", "args": {"result_number": n, "rel": "people"}}, ""),
                     search_fn(test_conn)).run("who is there?", Previous(query=prev.query, results=prev.results))
    assert len(invented.results) == 3 and invented.tools  # an unknown rel means all, not a fallback


def test_the_model_sees_the_numbered_results(test_conn, graph):
    prev = previous_of(test_conn, "glucose")
    model = Scripted({"name": "related", "args": {"result_number": 1}}, "")
    Agent(test_conn, model, search_fn(test_conn)).run("who works with her?", prev)
    first = model.sent[0]
    assert [type(m).__name__ for m in first].count("SystemMessage") == 1  # the gateway rejects a second one
    context = first[0].content
    assert "Last search: glucose" in context and f"#1 [person] {prev.results[0].name}" in context
    assert "Previous user message: glucose" in context  # for "her", as text, not as chat messages
    assert [type(m).__name__ for m in first] == ["SystemMessage", "HumanMessage"]
    assert any(isinstance(m, ToolMessage) for m in model.sent[1])


@pytest.mark.parametrize("answers", [
    [RuntimeError("gateway down")],                              # model call fails
    ["I think Bob is great."],                                  # no tool call on a new message
    [{"name": "more_like", "args": {"result_number": 9}}],      # no #9
    [{"name": "search", "args": {"querry": "x"}}],              # bad arguments
    [{"name": "delete_everything", "args": {}}],                # unknown tool
    [{"name": "search", "args": {"query": "zebrafish"}}] * 4,   # never stops: round cap
])
def test_fallback_is_a_plain_search_of_the_message(test_conn, graph, answers):
    prev = previous_of(test_conn, "glucose")
    turn = Agent(test_conn, Scripted(*answers), search_fn(test_conn)).run("insulin", prev)
    assert turn.query == "insulin"
    assert {"Diabetes Lab", "ARTORG Center"} <= set(names(turn))
    assert turn.reply == f"Showing {len(turn.results)} results for 'insulin'."


def test_reply_check(test_conn, graph):
    results = previous_of(test_conn, "glucose").results
    bob = next(r for r in results if r.name == "Bob Beispiel")
    claim = bob.evidence[0].claim_id
    assert check_reply("Showing glucose experts at DCB.", results) == "Showing glucose experts at DCB."
    assert check_reply("Bob Beispiel is the best expert.", results) is None  # names a result, no citation
    assert check_reply(f"Bob Beispiel works on glucose sensors [{claim}].", results)
    assert check_reply("Glucose experts [99999].", results) is None  # cites a claim that is not shown
    assert check_reply("x" * 300, results) is None
    assert check_reply("Showing who works with Bob Beispiel.", [], earlier=results) is None  # a previous result


def test_model_reply_kept_when_it_passes_the_check(test_conn, graph):
    model = Scripted({"name": "search", "args": {"query": "glucose", "source": "dcb"}}, "Showing glucose experts at DCB.")
    turn = Agent(test_conn, model, search_fn(test_conn)).run("glucose at DCB", Previous())
    assert turn.reply == "Showing glucose experts at DCB." and turn.filters == ChatFilters(source="dcb")

    model = Scripted({"name": "search", "args": {"query": "glucose"}}, "Bob Beispiel is the top expert.")
    turn = Agent(test_conn, model, search_fn(test_conn)).run("glucose", Previous())
    assert turn.reply.startswith("Showing ")  # failed the check: template


def test_describe_and_template():
    assert describe([]) == "(none)"
    assert template([], 0, "glucose", ChatFilters(type="person")) == "Showing 0 results for 'glucose' (type: person)."


def test_tool_schemas_bind_to_the_real_model():
    """The production model takes the four tool schemas (no gateway call)."""
    from navigator.core.settings import Settings

    model = agent.chat_model(Settings(keera_api_key="test"))
    names_bound = [t["function"]["name"] for t in model.kwargs["tools"]]
    assert names_bound == ["search", "set_filters", "more_like", "related"]


client = test_api.client  # the API fixture


def test_api_resolves_n_against_the_previous_stored_turn(client, graph):
    """Two requests, as on two workers: the 2nd reads the 1st from chat_turn (#103) and resolves "#n" there."""
    from fake_chat import SearchModel

    from navigator.api import app
    from navigator.api.deps import get_chat_model

    first = client.post("/api/chat", json={"session_id": "s1", "message": "glucose"}).json()
    n = [r["name"] for r in first["results"]].index("Alice Muster") + 1
    app.dependency_overrides[get_chat_model] = lambda: Scripted({"name": "related", "args": {"result_number": n}}, "")
    second = client.post("/api/chat", json={"session_id": "s1", "message": f"who works with #{n}?"}).json()
    assert [r["name"] for r in second["results"]] == ["Diabetes Lab", "Artificial Pancreas"]  # member_of, works_on
    assert second["reply"] == f"Showing 2 results linked to #{n} Alice Muster."

    app.dependency_overrides[get_chat_model] = lambda: SearchModel()
    other = client.post("/api/chat", json={"session_id": "s2", "message": "insulin"}).json()
    assert "Alice Muster" not in [r["name"] for r in other["results"][:1]]  # another session, its own turn


@pytest.mark.parametrize(("text", "call"), [
    ('set_filters(source="dcb")', ("set_filters", {"source": "dcb"})),
    ("related(result_number=1)", ("related", {"result_number": 1})),
    ("`more_like(result_number=2)`", ("more_like", {"result_number": 2})),
    ("search(query='glucose sensors', type=null)", ("search", {"query": "glucose sensors", "type": None})),
    ("related with result #2", ("related", {"result_number": 2})),
    ("more_like the first one, #1", ("more_like", {"result_number": 1})),
    ("Showing results for glucose.", None),
    ("I found #2 interesting", None),
    ("delete(all=1)", None),
])
def test_text_tool_call(text, call):
    found = text_tool_call(text)
    assert (found and (found["name"], found["args"])) == call or (found is None and call is None)


def test_a_call_written_as_text_runs_as_a_tool(test_conn, graph):
    prev = previous_of(test_conn, "glucose")
    turn = Agent(test_conn, Scripted('set_filters(source="dcb")', ""), search_fn(test_conn)).run("only DCB", prev)
    assert turn.filters == ChatFilters(source="dcb") and [r.name for r in turn.results] == ["Bob Beispiel"]
