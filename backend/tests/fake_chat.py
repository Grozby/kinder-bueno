"""Scripted chat models for the chat agent (#97): no gateway in the tests."""

from langchain_core.messages import AIMessage, HumanMessage


class Scripted:
    """Answers with the given AI messages in order; records what it was sent. A string is a reply, a dict a
    tool call ({"name": ..., "args": ...})."""

    def __init__(self, *answers):
        self.answers, self.sent = list(answers), []

    def invoke(self, messages):
        self.sent.append(messages)
        a = self.answers.pop(0) if self.answers else ""
        if isinstance(a, Exception):
            raise a
        if isinstance(a, dict):
            return AIMessage("", tool_calls=[{"name": a["name"], "args": a.get("args", {}), "id": f"c{len(self.sent)}"}])
        return AIMessage(a)


class SearchModel:
    """The plain-search behaviour (#50) the API tests expect: `search` with the user's message, then no reply."""

    def invoke(self, messages):
        if isinstance(messages[-1], HumanMessage):
            return AIMessage("", tool_calls=[{"name": "search", "args": {"query": messages[-1].content}, "id": "s"}])
        return AIMessage("")
