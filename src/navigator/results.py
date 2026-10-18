"""Turn ranked entity ids into Result objects (plan 8.8), using shown claims and relations only."""

from collections import defaultdict

import psycopg

from navigator.models import Evidence, Result


def shown(alias: str) -> str:
    """SQL condition for a shown claim or relation (plan 7.1)."""
    return f"{alias}.verified AND {alias}.judge_verdict IS DISTINCT FROM 'unsupported'"


REL_FIELDS = {
    "member_of": "affiliations",
    "listed_in": "affiliations",  # listed on the unit's member page (#23)
    "part_of": "affiliations",
    "works_on": "projects",
    "provides": "infrastructure",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _load(conn: psycopg.Connection, ids: list[int]) -> tuple[dict, dict, dict]:
    """Entities, shown claims (with page URL) and shown relation targets, keyed by entity id."""
    entities = {
        r[0]: r[1:]
        for r in conn.execute("SELECT id, type, name FROM entity WHERE id = ANY(%s)", (ids,))
    }
    claims = defaultdict(list)
    for row in conn.execute(
        f"""
        SELECT c.entity_id, c.id, c.field, c.value, c.quote, p.url, c.judge_verdict, c.judge_reason
        FROM claim c JOIN page p ON p.id = c.page_id
        WHERE c.entity_id = ANY(%s) AND {shown("c")}
        ORDER BY c.entity_id, c.id
        """,
        (ids,),
    ):
        claims[row[0]].append(Evidence(
            claim_id=row[1], field=row[2], value=row[3], quote=row[4],
            url=row[5], judge_verdict=row[6], judge_reason=row[7],
        ))
    related = defaultdict(lambda: defaultdict(list))
    for from_id, rel, name in conn.execute(
        f"""
        SELECT r.from_id, r.rel, t.name
        FROM relation r JOIN entity t ON t.id = r.to_id
        WHERE r.from_id = ANY(%s) AND {shown("r")}
        ORDER BY r.from_id, r.id
        """,
        (ids,),
    ):
        related[from_id][REL_FIELDS[rel]].append(name)
    return entities, claims, related


def _default_why(evidence: list[Evidence]) -> str:
    """Template from plan 8.6: first 2 expertise values (any claim values if there is no expertise)."""
    values = _unique([e.value for e in evidence if e.field == "expertise"]) or _unique([e.value for e in evidence])
    return "Matches on: " + ", ".join(values[:2])


def build_results(
    conn: psycopg.Connection, ranked: list[tuple[int, float]], why: dict[int, str] | None = None
) -> list[Result]:
    """Build results in the given rank order. Entities with no shown claims are skipped (plan 8.7)."""
    ids = [entity_id for entity_id, _ in ranked]
    entities, claims, related = _load(conn, ids)
    why = why or {}
    results = []
    for entity_id, score in ranked:
        evidence = claims.get(entity_id)
        if entity_id not in entities or not evidence:
            continue
        etype, name = entities[entity_id]

        def values(*fields: str) -> list[str]:
            return _unique([e.value for e in evidence if e.field in fields])

        rel = related.get(entity_id, {})
        results.append(Result(
            entity_id=entity_id,
            type=etype,
            name=name,
            role=values("role"),
            contact=values("email", "phone"),
            affiliations=_unique(rel.get("affiliations", [])),
            expertise=values("expertise"),
            projects=_unique(rel.get("projects", [])),
            infrastructure=_unique(rel.get("infrastructure", [])),
            why=why.get(entity_id) or _default_why(evidence),
            score=score,
            sources=_unique([e.url for e in evidence]),
            evidence=evidence,
        ))
    return results
