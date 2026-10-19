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

from navigator.verify import PageText, norm

TITLES = {"prof", "dr", "pd", "med", "phil", "nat", "rer", "sc", "phd", "md", "msc", "bsc", "dipl", "ing",
          "ass", "assoc", "asst", "em", "dent", "dr.-ing",  # "Ass. Prof. Dr." and "Prof. Dr." are one person (#75)
          "et", "habil", "h.c", "mult"}  # "Dr. med. et phil. nat.", "Dr. habil.", "Dr. h.c. mult." (#150)
# Words that label a list on member pages; the 8B model sometimes turns them into "people".
LABEL_WORDS = {"alumni", "phone", "phone2", "mail", "e-mail", "funktion", "name", "titel", "staff", "students",
               "student", "senior", "members", "member", "group", "team", "head", "chair", "administration",
               "candidates", "thesis", "master", "bachelor", "postdocs", "contact", "leader", "lead"}
# A name with one of these words is an organisation, not a person ("Balmer Lab", "Medová group") (#150)
ORG_WORDS = {"lab", "labs", "laboratory", "laboratories", "group", "groups", "team", "center", "centre", "institute",
             "department", "clinic", "unit", "office", "facility", "university", "hospital", "foundation", "ag",
             "gmbh"}

Mention = tuple[str, str, int]  # (entity_type, raw name, page_id)

# Member pages (#23): ".../<lab>/group_members/index_eng.html" or ".../team/". The lab is named on the parent page.
MEMBER_PAGE = re.compile(r"^(.*/)(?:group_members|team)/(index_eng\.html)?$")
# A person's profile under a lab (#75): ".../group_members/persons/dr_debeire_kevin/index_eng.html"
PROFILE_PAGE = re.compile(r"/group_members/(?:persons/)?[a-z]+_[a-z0-9_]+/(index_eng\.html)?$")
FIXED_UNITS = {"https://www.dcberne.com/en/team/": "Diabetes Center Berne"}  # its parent page starts with a slogan
MEMBER_REL = ("member_of", "listed_in")  # both give a person's unit
LAB_TOPIC_FIELDS = ("expertise", "description")  # moved from the umbrella to the lab on the lab's own pages (#70)


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
    email_sources: dict[str, defaultdict] = defaultdict(lambda: defaultdict(set))  # norm name -> email -> sources
    by_name: dict[str, list[Mention]] = defaultdict(list)
    for m, p in people.items():
        if p.emails:
            keys[m] = "email:" + min(p.emails)
            email_units[norm_name(p.name)][min(p.emails)] |= p.units
            email_sources[norm_name(p.name)][min(p.emails)].add(p.source)
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
            sources = {people[m].source for m in members}
            # Rule 3: merge into the one email person of the same name that shares a unit, else a source
            # (same-source name-only mentions merge too, rule 2). Two candidates: keep apart.
            matches = [e for e, e_units in email_units.get(name, {}).items() if units & e_units]
            if not matches:
                matches = [e for e, e_srcs in email_sources.get(name, {}).items() if sources & e_srcs]
            if len(matches) == 1:
                key = "email:" + matches[0]
            elif len(clusters) > 1:
                key = f"name:{name}#{min(people[m].source for m in members)}"
            else:
                key = "name:" + name
            for m in members:
                keys[m] = key
    return keys


def parent_url(url: str) -> str | None:
    """The unit page a member page belongs to: the URL without `group_members/` or `team/`. None if not a member page."""
    m = MEMBER_PAGE.match(url)
    return m.group(1) + (m.group(2) or "") if m else None


def is_person_name(name: str) -> bool:
    """A real person's name: at least two words after titles, no digits, not only list labels, no organisation word.
    Rejects "Alumni", "Phone2", "PhD Students", "Balmer Lab", and lone surnames that cannot be told apart. Used by
    extraction (claims and relations) and by resolve (listed_in), so both apply the same rule."""
    words = norm_name(name).replace("/", " ").replace("&", " ").split()
    return (len(words) >= 2 and not any(ch.isdigit() for ch in name) and not set(words) <= LABEL_WORDS
            and not ORG_WORDS & set(words))


looks_like_person = is_person_name  # the listed_in guard


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def member_page_rows(conn: psycopg.Connection, claims: list) -> tuple[list, list, Counter]:
    """`listed_in` rows for people with a verified claim on a unit's member page (#23).

    Returns extra claims and relations in the raw row shapes of _load: the unit's name (quote: the first line
    of the parent page, or the fixed name on the member page), and per person a `listed_in` relation plus a
    `listed_in` claim as its evidence row (quote: the person's name on the member page).
    """
    people: dict[int, set[str]] = defaultdict(set)
    for etype, name, page_id, *_ in claims:
        if etype == "person" and looks_like_person(name):
            people[page_id].add(name)
    pages = {
        url: (pid, title or "", text, source)
        for pid, url, title, text, source in conn.execute("SELECT id, url, title, text, source_id FROM page")
    }
    extra_claims, extra_relations, counts = [], [], Counter()
    for url, (page_id, title, text, source) in pages.items():
        parent = parent_url(url)
        if parent is None or not people.get(page_id):
            continue
        member_page = PageText(f"{title}\n{text}")
        if url in FIXED_UNITS:
            unit, unit_page = FIXED_UNITS[url], page_id
            unit_quote = member_page.rebuild_quote(unit, "name", unit)
        elif parent in pages:
            unit_page, p_title, p_text, _ = pages[parent]
            unit = first_line(p_text)
            unit_quote = PageText(f"{p_title}\n{p_text}").find_quote(unit) if unit else None
        else:
            counts["member pages skipped (no parent page)"] += 1
            continue
        if not unit_quote or not unit_quote.ok:
            counts["member pages skipped (unit name not found)"] += 1
            continue
        extra_claims.append(("unit", unit, unit_page, source, "name", unit, unit_quote.quote))
        for name in sorted(people[page_id]):
            quote = member_page.rebuild_quote(name, "name", name)
            if quote is None:
                continue
            extra_relations.append(("person", name, "listed_in", "unit", unit, page_id, source, quote.quote))
            extra_claims.append(
                ("person", name, page_id, source, "listed_in", f"listed on the member page of {unit}", quote.quote)
            )
    return extra_claims, extra_relations, counts


def site_name(title: str) -> str:
    """"Research: Adaptive Diabetes Management - ARTORG Center for ..." -> "ARTORG Center for ..."; "" if none."""
    return title.rsplit(" - ", 1)[1].strip() if " - " in title else ""


def move_umbrella_topics(conn: psycopg.Connection, claims: list, listed_relations: list) -> tuple[list, int, int]:
    """Give a lab the topic claims the extractor credited to the umbrella unit on the lab's own pages (#70).

    A lab's pages (".../research/aihn/...", the folder of its member page) often do not name the lab; only the
    page title names the site ("... - ARTORG Center ..."), so the extractor credits the site. A unit claim whose
    name is part of the page title's site name, on a page under a lab's folder, moves to that lab (the deepest
    folder wins). The quote is unchanged: it is still exact page text. On a person's profile page those topics
    are the person's (#75), already extracted as theirs: they are dropped, not moved to the lab.
    Returns the claims, the number moved and the number dropped.
    """
    pages = {pid: (url, title or "") for pid, url, title in conn.execute("SELECT id, url, title FROM page")}
    homes: dict[str, str] = {}  # lab folder -> lab name, from the member pages
    for _, _, _, _, lab, page_id, _, _ in listed_relations:
        m = MEMBER_PAGE.match(pages[page_id][0])
        if m:
            homes[m.group(1)] = lab
    moved, dropped, out = 0, 0, []
    for row in claims:
        etype, name, page_id, source, fld, value, quote = row
        url, title = pages[page_id]
        site = norm_unit(site_name(title))
        if etype == "unit" and fld in LAB_TOPIC_FIELDS and site and norm_unit(name) in site:
            owners = [folder for folder in homes if url.startswith(folder)]
            if owners and PROFILE_PAGE.search(url):
                dropped += 1
                continue
            if owners:
                lab = homes[max(owners, key=len)]
                if norm_unit(lab) != norm_unit(name):
                    row, moved = (etype, lab, page_id, source, fld, value, quote), moved + 1
        out.append(row)
    return out, moved, dropped


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


def acronym_aliases(unit_names: dict[str, str]) -> dict[str, str]:
    """{acronym key: full key} for unit names like "DCB" whose letters are the initials of exactly one other
    unit ("Diabetes Center Berne"). `unit_names` maps key -> a display name. No other fuzzy matching."""
    initials: dict[str, list[str]] = defaultdict(list)
    for key in unit_names:
        words = [w for w in re.split(r"[\s,&-]+", key) if w and w not in {"for", "of", "and", "the"}]
        if len(words) >= 2:
            initials["".join(w[0] for w in words)].append(key)
    return {
        key: initials[key][0]
        for key, name in unit_names.items()
        if name.isupper() and " " not in key and len(initials.get(key, [])) == 1
    }


def unit_variant(key: str) -> str:
    """"acoustic robotic systems lab (arsl)" -> "acoustic robotic system lab": no trailing "(...)", no plural "s"."""
    words = re.sub(r"\s*\([^)]*\)$", "", key).split()
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words)


def variant_aliases(mentions: Counter) -> dict[str, str]:
    """{key: key} merging unit keys that differ only by a plural "s" or a trailing "(ACRONYM)" ("Neuro Robotic
    Group", "Neuro Robotics Group") into the most mentioned one of them (#75). `mentions` counts mentions per key.
    Only these duplicates get another key, so the other units keep their ids."""
    groups: dict[str, list[str]] = defaultdict(list)
    for key in mentions:
        groups[unit_variant(key)].append(key)
    out = {}
    for keys in groups.values():
        if len(keys) > 1:
            main = max(keys, key=lambda k: (mentions[k], -len(k), k))
            out |= {k: main for k in keys if k != main}
    return out


# "spn-005 - pilot study on painless glucose monitoring": a project code, a dash (unidecode turns "–" into "-") or a
# colon, then its title
PROJECT_CODE = re.compile(r"^([a-z]{2,8}-?\d{1,4}[a-z]?)(?:\s+-\s+|\s*:\s*)(.+)$")


def project_code_aliases(project_keys: set[str]) -> dict[str, str]:
    """{code key: full key} for a project named by its code alone ("SPN-005" on its own page) when exactly one
    other project is "<code> – <title>" (the listing pages). No other fuzzy matching."""
    full: dict[str, list[str]] = defaultdict(list)
    for key in project_keys:
        if m := PROJECT_CODE.match(key):
            full[m.group(1)].append(key)
    return {code: keys[0] for code, keys in full.items() if code in project_keys and len(keys) == 1}


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
        if ftype == "person" and rel in MEMBER_REL:
            people[m].units.add(norm_unit(tname))
    variants = variant_aliases(Counter(k for m, k in keys.items() if m[0] == "unit"))
    keys = {m: variants.get(k, k) if m[0] == "unit" else k for m, k in keys.items()}
    aliases = acronym_aliases({k: name for (etype, name, _), k in keys.items() if etype == "unit"})
    codes = project_code_aliases({k for m, k in keys.items() if m[0] == "project"})
    keys = {m: (aliases if m[0] == "unit" else codes if m[0] == "project" else {}).get(k, k) for m, k in keys.items()}
    for p in people.values():
        p.units = {aliases.get(variants.get(u, u), variants.get(u, u)) for u in p.units}
    return keys | person_keys(people)


def _display_name(names: Counter) -> str:
    """The most common raw name; on a tie not an acronym ("Diabetes Center Berne" over "DCB"), else the first seen."""
    return max(names.items(), key=lambda kv: (kv[1], not kv[0].isupper()))[0]


def resolve(conn: psycopg.Connection) -> Counter:
    """Rebuild entity, claim and relation from the raw tables. Returns counts for the report."""
    claims, relations = _load(conn)
    listed_claims, listed_relations, counts = member_page_rows(conn, claims)
    claims, counts["lab topics moved from the umbrella"], counts["umbrella topics dropped on profiles"] = (
        move_umbrella_topics(conn, claims, listed_relations)
    )
    claims, relations = claims + listed_claims, relations + listed_relations
    keys = mention_keys(claims, relations)
    names: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for (etype, name, _), key in keys.items():
        names[(etype, key)][name] += 1

    with conn.transaction():
        conn.execute("DELETE FROM claim")
        conn.execute("DELETE FROM relation")
        ids: dict[tuple[str, str], int] = {}
        for (etype, key), counter in names.items():
            ids[(etype, key)] = conn.execute(
                "INSERT INTO entity (type, name, norm_key) VALUES (%s, %s, %s) "
                "ON CONFLICT (type, norm_key) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                (etype, _display_name(counter), key),
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
    counts["relations (listed_in)"] = conn.execute("SELECT count(*) FROM relation WHERE rel = 'listed_in'").fetchone()[0]
    counts["people without a unit"] = conn.execute(
        "SELECT count(*) FROM entity e WHERE e.type = 'person' AND NOT EXISTS "
        "(SELECT 1 FROM relation r WHERE r.from_id = e.id AND r.rel = ANY(%s))",
        (list(MEMBER_REL),),
    ).fetchone()[0]
    return counts
