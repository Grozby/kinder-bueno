#!/usr/bin/env bash
# Build the submission (#116): the technical report, docs/REPORT.md printed to PDF.
#
#   scripts/submission.sh      # writes dist/technical-report.pdf
#
# The report is printed with headless Chrome (CHROME=/path/to/chrome to use another one). Re-run
# `navigator eval` and `navigator case-eval` first and update the numbers in docs/REPORT.md, so they match eval/.
set -euo pipefail
cd "$(dirname "$0")/.."

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 0 ]] || die "usage: scripts/submission.sh"
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
[[ -x "$CHROME" ]] || CHROME=$(command -v google-chrome || command -v chromium || true)
[[ -n "$CHROME" && -x "$CHROME" ]] || die "Chrome not found: set CHROME=/path/to/chrome"

out=dist/technical-report.pdf
mkdir -p dist
rm -f "$out"

uv run --quiet --with markdown python scripts/report_html.py docs/REPORT.md dist/report.html
# The budget gives mermaid time to draw the diagram before printing
"$CHROME" --headless --disable-gpu --no-pdf-header-footer --virtual-time-budget=15000 \
  --print-to-pdf="$out" "file://$PWD/dist/report.html" 2>/dev/null
[[ -s "$out" ]] || die "printing the report failed"
ls -l "$out"
