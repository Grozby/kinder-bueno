"""Crawl rules per source, edited in the UI (GET/PUT /api/sources/{id}/rules, #79).

The defaults are the source's block in config/sources.yaml, or its stored config for a source added from
the UI (#55). A PUT stores all four lists in `source_rules`; from then on they replace the defaults, also
for the crawler (`with_stored`), so a re-crawl (#80) uses them.

A block applies at once: `page.blocked` is set for every stored page whose URL matches an exclude pattern
(`re.search`, as the crawler matches). results.shown() skips claims and relations from blocked pages, so
search, chat, case references and the eval drop them without a re-crawl. Case scores computed before a
block are not recomputed.
"""

import re
from datetime import UTC, datetime

import psycopg
from psycopg.types.json import Jsonb

from navigator.models import CrawlRules, CrawlRulesUpdate
from navigator.pages import SourceRules
from navigator.sources import SourceConfig, SourcesFile, _compile

KINDS = ("allow_hosts", "include_patterns", "exclude_patterns", "priority_patterns")


class RulesError(ValueError):
    """The rules cannot be stored: a pattern does not compile, or no host rule is left."""


def _default(conn: psycopg.Connection, sources: SourcesFile, source_id: str) -> SourceConfig | None:
    """The source's config before any stored rules: sources.yaml, else the config of a UI-added source."""
    try:
        return sources.get(source_id)
    except KeyError:
        row = conn.execute("SELECT config FROM source WHERE id = %s", (source_id,)).fetchone()
        return SourceConfig(**row[0]["source"]) if row and row[0] else None


def _stored(conn: psycopg.Connection, source_id: str) -> tuple[dict, datetime] | None:
    row = conn.execute("SELECT rules, changed_at FROM source_rules WHERE source_id = %s", (source_id,)).fetchone()
    return (row[0], row[1]) if row else None


def with_stored(conn: psycopg.Connection, config: SourceConfig) -> SourceConfig:
    """The config with the stored rules, if any: what the crawler uses."""
    stored = _stored(conn, config.id)
    return config.model_copy(update=stored[0]) if stored else config


def get_rules(conn: psycopg.Connection, sources: SourcesFile, source_id: str) -> CrawlRules | None:
    """The source's current rules; None for an unknown source."""
    config = _default(conn, sources, source_id)
    if config is None:
        return None
    stored = _stored(conn, source_id)
    current = config.model_copy(update=stored[0]) if stored else config
    return CrawlRules(**{k: getattr(current, k) for k in KINDS}, changed_at=stored[1] if stored else None)


def validate(config: SourceConfig, update: CrawlRulesUpdate) -> None:
    """RulesError naming the first pattern that does not compile, or when no host rule is left."""
    for kind in ("include_patterns", "exclude_patterns", "priority_patterns"):
        for pattern in getattr(update, kind):
            try:
                _compile(pattern)
            except ValueError as exc:
                raise RulesError(f"{kind}: {exc}") from exc
    if not update.allow_hosts and not config.allow_hosts_regex:
        raise RulesError("allow_hosts: at least one host is needed")


def save_rules(conn: psycopg.Connection, sources: SourcesFile, source_id: str,
               update: CrawlRulesUpdate) -> CrawlRules | None:
    """Store the rules (changed_at = now) and apply the blocks; None for an unknown source."""
    config = _default(conn, sources, source_id)
    if config is None:
        return None
    validate(config, update)
    rules = {k: [v.strip() for v in getattr(update, k) if v.strip()] for k in KINDS}
    now = datetime.now(UTC)
    conn.execute(
        """INSERT INTO source_rules (source_id, rules, changed_at) VALUES (%s, %s, %s)
           ON CONFLICT (source_id) DO UPDATE SET rules = EXCLUDED.rules, changed_at = EXCLUDED.changed_at""",
        (source_id, Jsonb(rules), now),
    )
    apply_blocks(conn, source_id, rules["exclude_patterns"])
    return CrawlRules(**rules, changed_at=now)


def first_match(patterns: list[str], url: str) -> str | None:
    return next((p for p in patterns if re.search(p, url)), None)


def apply_blocks(conn: psycopg.Connection, source_id: str, exclude: list[str]) -> int:
    """Set page.blocked for the source's pages from its current exclude patterns. Returns the count."""
    pages = conn.execute("SELECT id, url FROM page WHERE source_id = %s", (source_id,)).fetchall()
    blocked = [pid for pid, url in pages if first_match(exclude, url)]
    conn.execute("UPDATE page SET blocked = (id = ANY(%s)) WHERE source_id = %s", (blocked, source_id))
    return len(blocked)


def page_rules(conn: psycopg.Connection, sources: SourcesFile) -> dict[str, SourceRules]:
    """Exclude and priority patterns per source, for blocked_by / prioritised_by on the pages list (#78)."""
    out = {}
    for (source_id,) in conn.execute("SELECT id FROM source ORDER BY id").fetchall():
        rules = get_rules(conn, sources, source_id)
        if rules:
            out[source_id] = SourceRules(rules.exclude_patterns, rules.priority_patterns)
    return out
