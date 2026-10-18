"""Render a Markdown file to a standalone HTML page for printing (scripts/submission.sh, #116).

Mermaid blocks become diagrams in the browser (mermaid from jsdelivr), so print it with a JS-enabled browser.
"""

import html
import re
import sys
from pathlib import Path

import markdown

MERMAID = re.compile(r"```mermaid\n(.*?)```", re.S)

STYLE = """
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; font-size: 10.5pt; line-height: 1.45;
       color: #14213D; background: #fff; max-width: 180mm; margin: 0 auto; }
h1 { font-size: 20pt; margin: 0 0 4mm; } h2 { font-size: 14pt; margin: 7mm 0 2mm; border-bottom: 1px solid #DED9CE; }
table { border-collapse: collapse; margin: 3mm 0; font-size: 9.5pt; } th, td { border: 1px solid #DED9CE;
       padding: 1.2mm 2mm; text-align: left; vertical-align: top; } th { background: #F7F5F0; }
code { font-size: 9pt; background: #F7F5F0; padding: 0 1mm; } pre.mermaid { text-align: center; }
h2, table, pre { break-inside: avoid; }
"""


def render(md_text: str, title: str) -> str:
    blocks: list[str] = []

    def stash(m: re.Match) -> str:
        blocks.append(m.group(1))
        return f"\n\nMERMAIDBLOCK{len(blocks) - 1}\n\n"

    body = markdown.markdown(MERMAID.sub(stash, md_text), extensions=["tables", "fenced_code"])
    for i, src in enumerate(blocks):
        body = body.replace(f"<p>MERMAIDBLOCK{i}</p>", f'<pre class="mermaid">{html.escape(src)}</pre>')
    script = (
        '<script src="https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"></script>'
        "<script>mermaid.initialize({startOnLoad: true, theme: 'neutral'});</script>"
        if blocks else ""
    )
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f"<style>{STYLE}</style></head><body>{body}{script}</body></html>")


if __name__ == "__main__":
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    text = src.read_text()
    title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), src.stem)
    out.write_text(render(text, title))
