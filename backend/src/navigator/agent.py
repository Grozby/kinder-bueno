"""Chat agent (plan 8.10, #97): a LangGraph graph that refines a search by calling tools. It never writes facts.

The model only picks tools. Every answer is a list of result cards like /api/search, and the reply is one
sentence about what was done ("Showing 8 results similar to #1 Diabetes Center Berne."). Tools:

- search(query, source?, type?): a new topic, with the session's filters merged with the given ones
- set_filters(source?, type?): change the filters ("all" removes one), then re-run the last query
- more_like(result_number): search with that result's shown topics; the result itself is left out
- related(result_number, rel?): the people, units, projects and infrastructure linked to that result by
  shown relations, in both directions

"#2" is the 2nd result of the previous turn. The previous turn comes from `chat_turn` (#103), not from an
in-memory checkpointer: any API worker can answer the next message, and a restart loses nothing.

Guardrails (plan 8.10): at most MAX_ROUNDS tool rounds per message. A gateway error, a tool call with bad
arguments, a first message without a tool call, or the round cap used up → plain search of the message with the
current filters, so the chat is never worse than the search box. The model's reply is kept only if it cites
nothing but claim ids of the shown results and names no result without a citation; otherwise a template.
"""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Literal, TypedDict

import psycopg
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError, field_validator

from navigator.explain import cited_ids
from navigator.models import ChatFilters, EntityType, Expansion, Result, SearchResponse
from navigator.results import build_results, shown

log = logging.getLogger(__name__)

MAX_ROUNDS = 3          # tool rounds per user message (plan 8.10)
MAX_RELATED = 20        # results of `related`; a centre can have 60 members
SUMMARY_RESULTS = 10    # results listed to the model, numbered like the cards
MAX_REPLY = 240         # characters; longer replies are replaced by the template
RELATIONS = ("member_of", "listed_in", "part_of", "works_on", "provides")


# Tool schemas: the model sees the names, the docstrings and the fields.
class search(BaseModel):  # lower case: the class name is the tool name
    """Search experts, units, projects and infrastructure for a NEW topic."""
    query: str = Field(description="the topic, as a short search query")
    source: str | None = Field(None, description="only this source: artorg, dcb or unibe")
    type: EntityType | None = Field(None, description="only this result type")


class set_filters(BaseModel):
    """Change the filters of the last search and run it again, e.g. "only DCB", "only people", "all sources"."""
    source: str | None = Field(None, description='artorg, dcb, unibe, or "all" to remove the source filter')
    type: str | None = Field(None, description='person, unit, project, infrastructure, or "all" to remove it')


class more_like(BaseModel):
    """Find results similar to result #N of the last results ("more like #2", "similar to the first one")."""
    result_number: int = Field(description="N in #N, starting at 1")


class related(BaseModel):
    """The people, units, projects and infrastructure linked to result #N ("who works with #2?",
    "which lab is she in?", "what does this unit run?")."""
    result_number: int = Field(description="N in #N, starting at 1")
    rel: Literal[RELATIONS] | None = Field(None, description="only this relation; none = all")

    @field_validator("rel", mode="before")
    @classmethod
    def _known_rel(cls, value: object) -> object:
        """The model invents values ("people"): those mean all relations, not a failed call."""
        return value if value in RELATIONS else None


TOOLS = [search, set_filters, more_like, related]

SYSTEM = """You help users find research experts in Bern (ARTORG Center, Diabetes Center Berne, University of
Bern). You work ONLY by calling tools.
- A new topic → search.
- "only DCB", "only people", "all sources again" → set_filters.
- "more like #2", "similar to the second one" → more_like.
- "who works with her?", "who works with #2?", "which lab is he in?", "what does this unit run?" → related.
- Results are numbered #1, #2, ... in the LAST RESULTS below. Use only these numbers.
- "her", "him", "them", "it", "that lab" mean #1, unless the user's message names another result.
Never state facts about people, units or projects yourself.
After the tools, reply with ONE short sentence that says what you did, for example:
"Showing people at DCB for 'glucose sensors'." Do not list the results: the user sees them as cards."""

# A call written as text instead of a tool call: 'set_filters(source="dcb")', 'related(result_number=1)'.
# Apertus does this when the prompt shows calls as text; it is turned into a real call (arguments still checked).
TEXT_CALL = re.compile(r"^\W*(search|set_filters|more_like|related)\s*\((.*)\)\W*$", re.S)
TEXT_ARG = re.compile(r"""(\w+)\s*=\s*("[^"]*"|'[^']*'|-?\d+|null|None)""")
TEXT_REF = re.compile(r"^\W*(more_like|related)\b[^#]{0,40}#\s*(\d+)", re.S)  # "related with result #2"


def text_tool_call(content: object) -> dict | None:
    """The tool call in a text answer like 'related(result_number=1)', or None."""
    if not isinstance(content, str):
        return None
    if ref := TEXT_REF.match(content.strip()):
        return {"name": ref.group(1), "args": {"result_number": int(ref.group(2))}, "id": "text-call"}
    m = TEXT_CALL.match(content.strip())
    if not m:
        return None
    args: dict = {}
    for key, raw in TEXT_ARG.findall(m.group(2)):
        args[key] = None if raw in ("null", "None") else int(raw) if raw.lstrip("-").isdigit() else raw[1:-1]
    return {"name": m.group(1), "args": args, "id": "text-call"}


class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    query: str | None               # the last search query (set_filters re-runs it)
    previous_message: str | None    # the user's previous message, for "her" / "that lab"
    filters: ChatFilters
    results: list[Result]           # the results shown now; "#N" refers to these
    expansion: Expansion | None
    rounds: int
    done: list[str]                 # what the tools did this turn, for the template reply
    error: str | None               # set → fallback


@dataclass
class Turn:
    """The answer to one message, stored as a chat_turn by the caller."""
    reply: str
    query: str                      # what a blank message with new filters re-runs
    filters: ChatFilters
    results: list[Result]
    expansion: Expansion | None
    no_result: bool
    tools: list[str] = field(default_factory=list)  # tool calls made, for the log and the tests


@dataclass
class Previous:
    """The session's previous turn (from chat_turn), or an empty one for a new session."""
    query: str | None = None
    filters: ChatFilters = field(default_factory=ChatFilters)
    results: list[Result] = field(default_factory=list)
    message: str | None = None
    reply: str | None = None


Search = Callable[[str, ChatFilters], SearchResponse]


def describe(results: list[Result]) -> str:
    """The numbered list the model resolves "#2" against: "#1 [unit] Diabetes Center Berne — topics"."""
    lines = []
    for n, r in enumerate(results[:SUMMARY_RESULTS], start=1):
        topics = r.expertise or r.unit_topics or r.role
        lines.append(f"#{n} [{r.type}] {r.name}" + (f" — {', '.join(topics[:3])}" if topics else ""))
    return "\n".join(lines) or "(none)"


def _filters_text(f: ChatFilters) -> str:
    used = [f"{k}: {v}" for k, v in (("source", f.source), ("type", f.type)) if v]
    return f" ({', '.join(used)})" if used else ""


def template(done: list[str], n: int, query: str | None, filters: ChatFilters) -> str:
    """What the last tool did, in one sentence that states no facts about entities."""
    what = done[-1] if done else f"for '{query}'"
    return f"Showing {n} results {what}{_filters_text(filters)}."


def check_reply(text: str, results: list[Result], earlier: list[Result] = ()) -> str | None:
    """The model's sentence, if it only cites claim ids of the shown results and names no result (shown now, or
    in the previous turn) without a citation (plan 8.10, the check of 8.6); else None (use the template)."""
    text = " ".join((text or "").split())
    if not text or len(text) > MAX_REPLY:
        return None
    allowed = {e.claim_id for r in results for e in r.evidence}
    cited = cited_ids(text)
    if not cited <= allowed:
        return None
    if not cited and any(r.name.lower() in text.lower() for r in [*results, *earlier]):
        return None
    return text


def related_ids(conn: psycopg.Connection, entity_id: int, rel: str | None) -> list[int]:
    """Entities linked to `entity_id` by shown relations, both directions: units first, then projects,
    infrastructure and people; heads and professors before other people would need roles, so by name."""
    rows = conn.execute(
        f"""
        SELECT DISTINCT e.id, e.type, e.name FROM relation r
        JOIN entity e ON e.id = CASE WHEN r.from_id = %(id)s THEN r.to_id ELSE r.from_id END
        WHERE (r.from_id = %(id)s OR r.to_id = %(id)s) AND {shown("r")}
          AND (%(rel)s::text IS NULL OR r.rel = %(rel)s)
        """,
        {"id": entity_id, "rel": rel},
    ).fetchall()
    order = {"unit": 0, "project": 1, "infrastructure": 2, "person": 3}
    return [r[0] for r in sorted(rows, key=lambda r: (order.get(r[1], 9), r[2]))]


def _merge(filters: ChatFilters, source: str | None, type_: str | None) -> ChatFilters:
    """New filter values; "all" (or "any", "none") removes one, None keeps it."""
    def pick(old: str | None, new: str | None) -> str | None:
        if new is None:
            return old
        return None if new.strip().lower() in ("all", "any", "none", "") else new.strip().lower()
    return ChatFilters(source=pick(filters.source, source), type=pick(filters.type, type_))


class Agent:
    """One chat turn: `run(message, previous)`. `chat_model` is a LangChain chat model with the tools bound
    (`ChatOpenAI(...).bind_tools(TOOLS)` in the API); tests pass a scripted one."""

    def __init__(self, conn: psycopg.Connection, chat_model, search_fn: Search):
        self.conn, self.model, self.search_fn = conn, chat_model, search_fn
        graph = StateGraph(ChatState)
        graph.add_node("agent", self._agent)
        graph.add_node("tools", self._tools)
        graph.add_node("fallback", self._fallback)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._route, ["tools", "fallback", END])
        graph.add_conditional_edges("tools", lambda s: "fallback" if s["error"] else "agent", ["agent", "fallback"])
        graph.add_edge("fallback", END)
        self.graph = graph.compile()
        self._message = ""
        self._expansion: Expansion | None = None
        self._searched = False
        self._calls: list[str] = []

    # --- nodes ---------------------------------------------------------------------------------------------
    def _agent(self, state: ChatState) -> dict:
        # The previous exchange goes in as text: as chat messages, the model copies the earlier "Showing ..." reply
        # and calls no tool (seen on the gateway)
        context = (
            f"Previous user message: {state['previous_message'] or '(none)'}\n"
            f"Last search: {state['query'] or '(none)'}{_filters_text(state['filters'])}\n"
            f"Last results:\n{describe(state['results'])}"
        )
        try:
            # ONE system message: the gateway rejects a second one ("Invalid message role")
            answer = self.model.invoke([SystemMessage(f"{SYSTEM}\n\n{context}"), *state["messages"]])
        except Exception as e:  # gateway down, timeout: never fail the chat
            log.warning("chat agent: model call failed: %s", e)
            return {"error": "model"}
        if not getattr(answer, "tool_calls", None) and (call := text_tool_call(answer.content)):
            answer = AIMessage("", tool_calls=[call])
        return {"messages": [answer]}

    def _route(self, state: ChatState) -> str:
        if state["error"]:
            return "fallback"
        last = state["messages"][-1]
        calls = getattr(last, "tool_calls", None) or []
        if calls:
            return "tools" if state["rounds"] < MAX_ROUNDS else "fallback"
        # No tool call: fine after tools ran (the reply), not as the first answer to a new message
        if not self._searched:
            log.info("chat agent: no tool call, answer %r", str(last.content)[:200])
        return END if self._searched else "fallback"

    def _tools(self, state: ChatState) -> dict:
        update: dict = {"rounds": state["rounds"] + 1, "messages": []}
        query, filters, results, done = state["query"], state["filters"], state["results"], list(state["done"])
        for call in state["messages"][-1].tool_calls:
            name, args = call["name"], call.get("args") or {}
            self._calls.append(f"{name}({json.dumps(args, sort_keys=True)})")
            try:
                if name == "search":
                    a = search(**args)
                    filters = _merge(filters, a.source, a.type)
                    query = a.query
                    results = self._search(query, filters)
                    done.append(f"for '{query}'")
                elif name == "set_filters":
                    a = set_filters(**args)
                    filters = _merge(filters, a.source, a.type)
                    if not query:
                        raise ValueError("no search to filter yet")
                    results = self._search(query, filters)
                    done.append(f"for '{query}'")
                elif name in ("more_like", "related"):
                    a = more_like(**args) if name == "more_like" else related(**args)
                    if not 1 <= a.result_number <= len(results):
                        raise ValueError(f"there is no #{a.result_number} (the last results have {len(results)})")
                    target = results[a.result_number - 1]
                    if name == "more_like":
                        topics = target.expertise or target.unit_topics or [target.name]
                        query = "; ".join(topics[:6])
                        results = [r for r in self._search(query, filters) if r.entity_id != target.entity_id]
                        done.append(f"similar to #{a.result_number} {target.name}")
                    else:
                        ids = related_ids(self.conn, target.entity_id, a.rel)
                        if filters.type:
                            types = dict(self.conn.execute(
                                "SELECT id, type FROM entity WHERE id = ANY(%s)", (ids,)).fetchall())
                            ids = [i for i in ids if types.get(i) == filters.type]
                        results = build_results(self.conn, [(i, 0.0) for i in ids[:MAX_RELATED]])
                        self._expansion = None
                        self._searched = True
                        done.append(f"linked to #{a.result_number} {target.name}")
                else:
                    raise ValueError(f"unknown tool {name}")
            except (ValidationError, TypeError, ValueError) as e:
                log.info("chat agent: bad tool call %s %s: %s", name, args, e)
                update["error"] = "tool"
                break
            update["messages"].append(ToolMessage(
                content=f"Done. Results now:\n{describe(results)}", tool_call_id=call.get("id") or name))
        return {**update, "query": query, "filters": filters, "results": results, "done": done}

    def _fallback(self, state: ChatState) -> dict:
        """Plain search of the message with the current filters (plan 8.10)."""
        query = self._message or state["query"] or ""
        results = self._search(query, state["filters"]) if query else []
        return {"query": query, "results": results, "done": [f"for '{query}'"], "error": "fallback",
                "messages": [AIMessage("")]}

    # --- helpers -------------------------------------------------------------------------------------------
    def _search(self, query: str, filters: ChatFilters) -> list[Result]:
        found = self.search_fn(query, filters)
        self._expansion = found.expansion
        self._searched = True
        return found.results

    def run(self, message: str, previous: Previous, filters: ChatFilters | None = None) -> Turn:
        """Answer one message. `filters` from the request replace the previous turn's (the UI's checkboxes)."""
        self._message = message.strip()
        state: ChatState = {
            "messages": [HumanMessage(self._message)],
            "query": previous.query, "previous_message": previous.message, "filters": filters or previous.filters,
            "results": previous.results, "expansion": None, "rounds": 0, "done": [], "error": None,
        }
        out = self.graph.invoke(state)
        results, query = out["results"], out["query"] or self._message
        text = out["messages"][-1].content if not out["error"] else ""
        reply = check_reply(text if isinstance(text, str) else "", results, previous.results) or template(
            out["done"], len(results), query, out["filters"])
        log.info("chat agent: %r → %s%s", self._message, ", ".join(self._calls) or "no tool call",
                 f" (fallback: {out['error']})" if out["error"] else "")
        return Turn(reply=reply, query=query, filters=out["filters"], results=results, expansion=self._expansion,
                    no_result=not results, tools=self._calls)


def chat_model(settings):
    """The production model: Apertus on the gateway, tools bound, deterministic (plan 8.10)."""
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(base_url=settings.llm_base_url, api_key=settings.keera_api_key,
                       model=settings.llm_model, temperature=0, timeout=20, max_retries=1)
    return model.bind_tools(TOOLS)
