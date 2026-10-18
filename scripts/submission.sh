#!/usr/bin/env bash
# Build the submission zip (#116): pitch slides, technical report (PDF), eval reports and the handoff guide.
#
#   scripts/submission.sh SLIDES.pdf SLIDES.pptx      # writes dist/submission.zip
#
# The slides are the "Research & Expertise Navigator" deck, downloaded as PDF and PPTX. docs/REPORT.md is
# printed to PDF with headless Chrome (CHROME=/path/to/chrome to use another one). Re-run `navigator eval` and
# `navigator case-eval` first and update the numbers in docs/REPORT.md and the slides, so they match eval/.
# checkpoints/ (the demo dump) is never included: it holds crawled page texts and goes to the challenge owner
# separately.
set -euo pipefail
cd "$(dirname "$0")/.."

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 2 ]] || die "usage: scripts/submission.sh SLIDES.pdf SLIDES.pptx"
slides_pdf=$1 slides_pptx=$2
[[ -f "$slides_pdf" && "$slides_pdf" == *.pdf ]] || die "$slides_pdf: not a PDF file"
[[ -f "$slides_pptx" && "$slides_pptx" == *.pptx ]] || die "$slides_pptx: not a PPTX file"
CHROME=${CHROME:-"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"}
[[ -x "$CHROME" ]] || CHROME=$(command -v google-chrome || command -v chromium || true)
[[ -n "$CHROME" && -x "$CHROME" ]] || die "Chrome not found: set CHROME=/path/to/chrome"

out=dist/submission
rm -rf "$out" dist/submission.zip
mkdir -p "$out/eval"

uv run --quiet --with markdown python scripts/report_html.py docs/REPORT.md dist/report.html
# The budget gives mermaid time to draw the diagram before printing
"$CHROME" --headless --disable-gpu --no-pdf-header-footer --virtual-time-budget=15000 \
  --print-to-pdf="$out/technical-report.pdf" "file://$PWD/dist/report.html" 2>/dev/null
[[ -s "$out/technical-report.pdf" ]] || die "printing the report failed"

cp "$slides_pdf" "$out/pitch-slides.pdf"
cp "$slides_pptx" "$out/pitch-slides.pptx"
cp docs/HANDOFF.md "$out/HANDOFF.md"
cp eval/report.md eval/case_report.md "$out/eval/"
# The tag if HEAD is tagged, else the commit: the code the report and the eval numbers describe
version=$(git describe --tags --exact-match 2>/dev/null || git rev-parse --short HEAD)
printf 'Code: https://github.com/Grozby/kinder-bueno at %s. Start with HANDOFF.md.\n' "$version" > "$out/README.txt"

(cd dist && zip -qr submission.zip submission)
unzip -l dist/submission.zip
