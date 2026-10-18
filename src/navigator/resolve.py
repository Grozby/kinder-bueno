"""Merge raw extractions into entity / claim / relation (PLAN 7.7).

Rebuilds the three tables from the verified rows of raw_claim and raw_relation on every run,
so it is idempotent. Entity ids stay stable across runs (upsert on type + norm_key).
No fuzzy matching: a few duplicates are fine, a wrong merge of two people is not.
"""

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import psycopg
from unidecode import unidecode

from navigator.verify import norm

TITLES = {"prof", "dr", "pd", "med", "phil", "nat", "rer", "sc", "phd", "md", "msc", "bsc", "dipl", "ing"}

Mention = tuple[str, str, int]  # (entity_type, raw name, page_id)


def norm_name(name: str) -> str:
    """Drop academic titles, transliterate to ASCII, lowercase, collapse spaces. Word order is kept."""
    words = re.split(r"[\s,]+", unidecode(name).lower())
    return " ".join(w for w in words if w and w.rstrip(".") not in TITLES)


def norm_unit(name: str) -> str:
    """Key for units, projects and infrastructure: norm_name without a leading "the "."""
    return re.sub(r"^the ", "", norm_name(name))


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b) -> None:
        self.parent[self.find(a)] = self.find(b)


@dataclass
class _Person:
    """What we know about one person mention (a name on one page)."""
    name: str
    source: str
    emails: set[str] = field(default_factory=set)
    units: set[str] = field(default_factory=set)  # unit keys via member_of


def person_keys(people: dict[Mention, _Person]) -> dict[Mention, str]:
    """norm_key per person mention, with the email / shared unit / same source rules of PLAN 7.7."""
    keys: dict[Mention, str] = {}
    email_units: dict[str, defaultdict] = defaultdict(lambda: defaultdict(set))  # norm name -> email -> units
    by_name: dict[str, list[Mention]] = defaultdict(list)
    for m, p in people.items():
        if p.emails:
            keys[m] = "email:" + min(p.emails)
            email_units[norm_name(p.name)][min(p.emails)] |= p.units
        else:
            by_name[norm_name(p.name)].append(m)

    for name, mentions in by_name.items():
        # Name-only mentions of the same name merge if they share a unit or a source.
        uf = _UnionFind()
        for i, a in enumerate(mentions):
            uf.find(a)
            for b in mentions[i + 1:]:
                if people[a].source == people[b].source or people[a].units & people[b].units:
                    uf.union(a, b)
        clusters: dict = defaultdict(list)
        for m in mentions:
            clusters[uf.find(m)].append(m)
        for members in clusters.values():
            units = set().union(*(people[m].units for m in members))
            # Rule 3: merge into the one email person of the same name that shares a unit.
            matches = [e for e, e_units in email_units.get(name, {}).items() if units & e_units]
            if len(matches) == 1:
                key = "email:" + matches[0]
            elif len(clusters) > 1:
                key = f"name:{name}#{min(people[m].source for m in members)}"
            else:
                key = "name:" + name
            for m in members:
                keys[m] = key
    return keys


def _load(conn: psycopg.Connection) -> tuple[list, list]:
    claims = conn.execute(
        "SELECT r.entity_type, r.entity_name, r.page_id, p.source_id, r.field, r.value, r.quote "
        "FROM raw_claim r JOIN page p ON p.id = r.page_id WHERE r.verified ORDER BY r.id"
    ).fetchall()
    relations = conn.execute(
        "SELECT r.from_type, r.from_name, r.rel, r.to_type, r.to_name, r.page_id, p.source_id, r.quote "
        "FROM raw_relation r JOIN page p ON p.id = r.page_id WHERE r.verified ORDER BY r.id"
    ).fetchall()
    return claims, relations


def mention_keys(claims: list, relations: list) -> dict[Mention, str]:
    """(type, name, page) -> norm_key for every entity named in a verified claim or relation."""
    keys: dict[Mention, str] = {}
    people: dict[Mention, _Person] = {}

    def add(etype: str, name: str, page_id: int, source: str) -> Mention:
        m = (etype, name, page_id)
        if etype == "person":
            people.setdefault(m, _Person(name, source))
        else:
            keys[m] = norm_unit(name)
        return m

    for etype, name, page_id, source, fld, value, _ in claims:
        m = add(etype, name, page_id, source)
        if etype == "person" and fld == "email":
            people[m].emails.add(value.strip().lower())
    for ftype, fname, rel, ttype, tname, page_id, source, _ in relations:
        m = add(ftype, fname, page_id, source)
        add(ttype, tname, page_id, source)
        if ftype == "person" and rel == "member_of":
            people[m].units.add(norm_unit(tname))
    return keys | person_keys(people)


def resolve(conn: psycopg.Connection) -> Counter:
    """Rebuild entity, claim and relation from the raw tables. Returns counts for the report."""
    claims, relations = _load(conn)
    keys = mention_keys(claims, relations)
    names: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for (etype, name, _), key in keys.items():
        names[(etype, key)][name] += 1

    counts: Counter = Counter()
    with conn.transaction():
        conn.execute("DELETE FROM claim")
        conn.execute("DELETE FROM relation")
        ids: dict[tuple[str, str], int] = {}
        for (etype, key), counter in names.items():
            ids[(etype, key)] = conn.execute(
                "INSERT INTO entity (type, name, norm_key) VALUES (%s, %s, %s) "
                "ON CONFLICT (type, norm_key) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (etype, counter.most_common(1)[0][0], key),
            ).fetchone()[0]
            counts[f"entities ({etype})"] += 1
        conn.execute("DELETE FROM entity WHERE NOT (id = ANY(%s))", (list(ids.values()),))

        def entity_id(etype: str, name: str, page_id: int) -> int:
            return ids[(etype, keys[(etype, name, page_id)])]

        claim_rows = {}
        for etype, name, page_id, _, fld, value, quote in claims:
            eid = entity_id(etype, name, page_id)
            claim_rows.setdefault((eid, fld, norm(value), page_id), (eid, fld, value, quote, page_id))
        relation_rows = set()
        for ftype, fname, rel, ttype, tname, page_id, _, quote in relations:
            frm, to = entity_id(ftype, fname, page_id), entity_id(ttype, tname, page_id)
            if frm != to:
                relation_rows.add((frm, rel, to, quote, page_id))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO claim (entity_id, field, value, quote, page_id, verified) "
                "VALUES (%s, %s, %s, %s, %s, true)",
                list(claim_rows.values()),
            )
            cur.executemany(
                "INSERT INTO relation (from_id, rel, to_id, quote, page_id, verified) "
                "VALUES (%s, %s, %s, %s, %s, true) ON CONFLICT DO NOTHING",
                sorted(relation_rows),
            )
    counts["claims"] = len(claim_rows)
    counts["relations"] = conn.execute("SELECT count(*) FROM relation").fetchone()[0]
    return counts
