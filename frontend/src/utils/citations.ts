// Claim-id citations in "why" sentences and pitches (#109): the backend keeps a sentence only when it
// cites claim ids like [11258], and every cited id is one of the reference's evidence rows.

import type { Evidence } from '@/api'

// A run of plain text, or one group of adjacent citations: "[11258][11259]", "[11258] [11259]" and
// "[11258, 11259]" are each one group (the forms explain.cited_ids accepts; CITATION_RUN in documents.py)
export type CitedPart = { text: string } | { n: number; ids: number[] }

const CITE = String.raw`\[\d+(?:\s*,\s*\d+)*\]`
const GROUP = new RegExp(`${CITE}(?:\\s*${CITE})*`, 'g')

// The text split into plain parts and citation groups, numbered 1, 2, … in reading order
export function splitCitations(text: string): CitedPart[] {
  const parts: CitedPart[] = []
  let last = 0
  let n = 0
  for (const m of text.matchAll(GROUP)) {
    if (m.index > last) parts.push({ text: text.slice(last, m.index) })
    parts.push({ n: ++n, ids: [...m[0].matchAll(/\d+/g)].map((d) => Number(d[0])) })
    last = m.index + m[0].length
  }
  if (last < text.length) parts.push({ text: text.slice(last) })
  return parts
}

// Claim id → evidence row, over every reference that can be cited
export function evidenceIndex(results: { evidence: Evidence[] }[]): Map<number, Evidence> {
  return new Map(results.flatMap((r) => r.evidence.map((e) => [e.claim_id, e] as const)))
}

// Plain text without the citations: for tooltips, where a marker cannot be clicked
export function withoutCitations(text: string): string {
  return text.replace(new RegExp(String.raw`\s*` + GROUP.source, 'g'), '')
}

// The text for the clipboard: each group becomes the numbers of its source pages, [1] or [1][2], one number
// per distinct page, and a "Sources" list at the end gives the pages. A group whose ids are not in the index
// stays as written, so no citation is lost silently.
export function withFootnotes(text: string, index: Map<number, Evidence>): string {
  const pages = new Map<string, number>()
  const body = splitCitations(text)
    .map((p) => {
      if ('text' in p) return p.text
      const rows = p.ids.map((id) => index.get(id))
      if (rows.some((e) => !e)) return p.ids.map((id) => `[${id}]`).join('')
      return [...new Set(rows.map((e) => e!.url))]
        .map((url) => `[${pages.get(url) ?? pages.set(url, pages.size + 1).get(url)}]`)
        .join('')
    })
    .join('')
  if (!pages.size) return body
  return `${body}\n\nSources:\n${[...pages].map(([url, n]) => `[${n}] ${url}`).join('\n')}`
}
