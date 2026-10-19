"""HTML → clean page text. The cleaned text is the ground truth for quote checks.

We take the visible text of the main content container, not a boilerplate remover
like trafilatura: on team pages trafilatura drops most names and contacts.
"""

import html as html_lib
import re
from dataclasses import dataclass
from urllib.parse import unquote, urldefrag, urljoin

from selectolax.lexbor import LexborHTMLParser, LexborNode

NOISE_TAGS = ["script", "style", "noscript", "nav", "header", "footer", "form", "svg", "iframe", "button"]
MAIN_SELECTORS = ["main", "[role=main]", "#main-content", "#main", "#content", "article"]
CHAR_CODES_RE = re.compile(r"String\.fromCharCode\(([\d,\s]+)\)")
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


@dataclass
class CleanPage:
    title: str
    text: str
    links: list[str]
    emails: list[str]


def decode_email_href(href: str) -> str | None:
    """Return the email behind a `mailto:` or a JavaScript `String.fromCharCode(...)` link."""
    href = href.strip()
    if m := CHAR_CODES_RE.search(href):
        candidate = "".join(chr(int(c)) for c in m.group(1).split(","))
    elif href.lower().startswith("mailto:"):
        candidate = unquote(href[len("mailto:"):]).split("?")[0]
    else:
        return None
    candidate = candidate.strip()
    return candidate.lower() if EMAIL_RE.match(candidate) else None


def _visible_lines(node: LexborNode) -> list[str]:
    lines = (re.sub(r"\s+", " ", line).strip() for line in node.text(separator="\n").split("\n"))
    return [line for line in lines if line]


def clean_html(raw_html: str, base_url: str) -> CleanPage:
    tree = LexborHTMLParser(raw_html)

    title_node = tree.css_first("title")
    title = re.sub(r"\s+", " ", title_node.text()).strip() if title_node else ""

    # Links are collected before noise removal: navigation menus are where most links live.
    links, emails = [], []
    for a in tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        email = decode_email_href(href)
        if email:
            if email not in emails:
                emails.append(email)
            # Write the email inline, next to the name it belongs to ("Mail" → address).
            if "@" not in a.text():
                a.replace_with(email)
            continue
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        url, _ = urldefrag(urljoin(base_url, html_lib.unescape(href.strip())))
        if url.startswith(("http://", "https://")) and url not in links:
            links.append(url)

    for tag in NOISE_TAGS:
        for node in tree.css(tag):
            node.decompose()

    root = next((n for sel in MAIN_SELECTORS if (n := tree.css_first(sel))), None) or tree.body
    lines = _visible_lines(root) if root else []

    missing = [e for e in emails if not any(e in line for line in lines)]
    if missing:
        lines += ["", "Contact emails on this page:"] + [f"- {e}" for e in missing]

    return CleanPage(title=title, text="\n".join(lines), links=links, emails=emails)
