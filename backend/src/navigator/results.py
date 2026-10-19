"""Turn ranked entity ids into Result objects (plan 8.8), using shown claims and relations only."""

from collections import defaultdict

import psycopg

from navigator.core.db import shown
from navigator.models import Evidence, Result
from navigator.ingest.verify import norm


REL_FIELDS = {
    "member_of": "affiliations",
    "listed_in": "affiliations",  # listed on the unit's member page (#23)
    "part_of": "affiliations",
    "works_on": "projects",
    "provides": "infrastructure",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


UNIT_LINKS = ("member_of", "listed_in")
MAX_TOPIC_UNITS = 2      # per person; the specific lab (listed_in) comes before broad member_of units
MAX_TOPICS_PER_UNIT = 5  # an umbrella unit ("ARTORG Center") can hold hundreds of topics


def _unit_topics(conn: psycopg.Connection, ids: list[int]) -> dict[int, list[Evidence]]:
    """Shown expertise claims of the units each entity is a shown member of / listed in (#44).
    They are the unit's topics, not the person's: rows carry via_unit and field "unit_expertise"."""
    topics: dict[int, list[Evidence]] = defaultdict(list)
    units: dict[int, list[int]] = defaultdict(list)  # person -> unit ids kept, in order
    values: dict[tuple[int, int], set[str]] = defaultdict(set)  # (person, unit) -> normalised values kept
    for row in conn.execute(
        f"""
        SELECT r.from_id, u.name, c.id, c.value, c.quote, p.url, c.judge_verdict, c.judge_reason, u.id
        FROM relation r
        JOIN entity u ON u.id = r.to_id
        JOIN claim c ON c.entity_id = u.id AND c.field = 'expertise' AND {shown("c")}
        JOIN page p ON p.id = c.page_id
        WHERE r.from_id = ANY(%s) AND r.rel = ANY(%s) AND {shown("r")}
        ORDER BY r.from_id, (r.rel = 'listed_in') DESC, r.id, c.id
        """,
        (ids, list(UNIT_LINKS)),
    ):
        person, unit_id, value = row[0], row[8], norm(row[3])
        if unit_id not in units[person]:
            if len(units[person]) >= MAX_TOPIC_UNITS:
                continue
            units[person].append(unit_id)
        kept = values[(person, unit_id)]
        if value in kept or len(kept) >= MAX_TOPICS_PER_UNIT:
            continue
        kept.add(value)
        topics[person].append(Evidence(
            claim_id=row[2], field="unit_expertise", value=row[3], quote=row[4], url=row[5],
            judge_verdict=row[6], judge_reason=row[7], via_unit=row[1],
        ))
    return topics


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


def _default_why(evidence: list[Evidence], unit_topics: list[Evidence]) -> str:
    """Template from plan 8.6: first 2 expertise values; else the unit's topics, worded as the unit's;
    else any claim values."""
    own = _unique([e.value for e in evidence if e.field == "expertise"])
    if own:
        return "Matches on: " + ", ".join(own[:2])
    if unit_topics:
        unit = unit_topics[0].via_unit
        values = _unique([e.value for e in unit_topics if e.via_unit == unit])
        return f"In {unit}, which works on: " + ", ".join(values[:2])
    return "Matches on: " + ", ".join(_unique([e.value for e in evidence])[:2])


def build_results(
    conn: psycopg.Connection, ranked: list[tuple[int, float]], why: dict[int, str] | None = None
) -> list[Result]:
    """Build results in the given rank order. Entities with no shown claims are skipped (plan 8.7)."""
    ids = [entity_id for entity_id, _ in ranked]
    entities, claims, related = _load(conn, ids)
    topics = _unit_topics(conn, [i for i in ids if entities.get(i, ("",))[0] == "person"])
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
        unit_topics = topics.get(entity_id, [])
        results.append(Result(
            entity_id=entity_id,
            type=etype,
            name=name,
            role=values("role"),
            contact=values("email", "phone"),
            affiliations=_unique(rel.get("affiliations", [])),
            expertise=values("expertise"),
            unit_topics=_unique([e.value for e in unit_topics]),
            projects=_unique(rel.get("projects", [])),
            infrastructure=_unique(rel.get("infrastructure", [])),
            why=why.get(entity_id) or _default_why(evidence, unit_topics),
            score=score,
            sources=_unique([e.url for e in evidence + unit_topics]),
            evidence=evidence + unit_topics,
        ))
    return results
