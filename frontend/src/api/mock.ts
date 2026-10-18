// In-memory stand-in for the backend, so the UI can be built and demoed before the API exists.
// All names are placeholders ("Muster" = Swiss "example"); none of this is real data.
import type {
  Case,
  CaseStatus,
  ChatRequest,
  ChatResponse,
  CrawledPage,
  EntityType,
  FeedbackRequest,
  NewSource,
  Pitch,
  Result,
  Source,
} from './types'

const ANALYSIS_MS = 3500
const CRAWL_MS = 9000

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const clone = <T>(value: T): T => structuredClone(value)

function hash(text: string): number {
  let h = 2166136261
  for (const ch of text) h = Math.imul(h ^ ch.charCodeAt(0), 16777619)
  return h >>> 0
}

// Deterministic pseudo-random numbers, so a given PDF always gets the same mock score
function rng(seed: number) {
  let s = seed || 1
  return () => {
    s = Math.imul(s ^ (s >>> 15), 2246822507) ^ Math.imul(s ^ (s >>> 13), 3266489909)
    return ((s ^= s >>> 16) >>> 0) / 4294967296
  }
}

const INDUSTRIES = ['MedTech', 'Digital Health', 'Biotech', 'Precision Engineering', 'Diagnostics']
const CRITERIA = [
  'Research fit',
  'Talent pool',
  'Infrastructure & labs',
  'Industry network',
  'Market access',
]

const REFERENCE_POOL: Array<[EntityType, string, string, string]> = [
  ['unit', 'Muster Lab for Surgical Robotics', 'ARTORG Center', 'artorg'],
  ['person', 'Prof. Dr. Anna Muster', 'ARTORG Center', 'artorg'],
  ['project', 'Smart Insulin Patch', 'Diabetes Center Berne', 'dcb'],
  ['infrastructure', 'Cleanroom & Prototyping Platform', 'University of Bern', 'unibe'],
  ['person', 'Dr. Luca Beispiel', 'Diabetes Center Berne', 'dcb'],
  ['unit', 'Institute for Muster Imaging', 'University of Bern', 'unibe'],
  ['project', 'Closed-Loop Glucose Control', 'Diabetes Center Berne', 'dcb'],
  ['person', 'PD Dr. Sara Exempel', 'University of Bern', 'unibe'],
  ['infrastructure', 'Biomechanics Testing Facility', 'ARTORG Center', 'artorg'],
  ['unit', 'Muster Group for Cardiovascular Engineering', 'ARTORG Center', 'artorg'],
  ['person', 'Dr. Jonas Platzhalter', 'ARTORG Center', 'artorg'],
  ['project', 'AI Nutrition Coach', 'Diabetes Center Berne', 'dcb'],
  ['unit', 'Department for Muster Medicine', 'University of Bern', 'unibe'],
  ['person', 'Prof. Dr. Mia Vorlage', 'University of Bern', 'unibe'],
  ['infrastructure', 'Translational Imaging Center', 'University of Bern', 'unibe'],
  ['project', 'Wearable Sensor Validation', 'ARTORG Center', 'artorg'],
  ['person', 'Dr. Noah Muster', 'Diabetes Center Berne', 'dcb'],
  ['unit', 'Innovation Office', 'University of Bern', 'unibe'],
  ['project', 'Gait Analysis Platform', 'ARTORG Center', 'artorg'],
  ['person', 'Dr. Lea Beispiel', 'University of Bern', 'unibe'],
  ['infrastructure', 'Clinical Trials Unit', 'University of Bern', 'unibe'],
  ['unit', 'Muster Lab for Hearing Research', 'ARTORG Center', 'artorg'],
  ['person', 'Prof. Dr. Tim Exempel', 'ARTORG Center', 'artorg'],
  ['project', 'Digital Twin of the Heart', 'ARTORG Center', 'artorg'],
  ['unit', 'Startup Accelerator', 'Diabetes Center Berne', 'dcb'],
  ['person', 'Dr. Eva Platzhalter', 'Diabetes Center Berne', 'dcb'],
  ['infrastructure', 'Biobank', 'University of Bern', 'unibe'],
  ['project', 'Robotic Cochlear Implantation', 'ARTORG Center', 'artorg'],
  ['unit', 'Center for Muster Data Science', 'University of Bern', 'unibe'],
  ['person', 'Dr. Ben Vorlage', 'University of Bern', 'unibe'],
]

const ROOT_URLS: Record<string, string> = {
  artorg: 'https://www.artorg.unibe.ch/index_eng.html',
  dcb: 'https://www.dcberne.com/en/',
  unibe: 'https://www.unibe.ch/index_eng.html',
}

const EXPERTISE: Record<string, string[]> = {
  artorg: ['surgical robotics', 'medical imaging', 'biomechanics', 'cardiovascular engineering'],
  dcb: ['diabetes technology', 'glucose monitoring', 'digital health', 'medical devices'],
  unibe: ['translational medicine', 'clinical research', 'data science', 'biomedical research'],
}

// The pool as search results; entity ids are stable, so chat results match case references
function toResult(i: number, why: string, score: number): Result {
  const [type, name, affiliation, sourceId] = REFERENCE_POOL[i]!
  const topics = EXPERTISE[sourceId]!
  return {
    entity_id: i + 1,
    type,
    name,
    role: type === 'person' ? ['Researcher'] : [],
    contact: [],
    affiliations: [affiliation],
    expertise: [topics[i % topics.length]!, topics[(i + 1) % topics.length]!],
    projects: [],
    infrastructure: [],
    why,
    score,
    sources: [ROOT_URLS[sourceId]!],
    unit_topics: type === 'person' ? [topics[(i + 2) % topics.length]!] : [],
    evidence: [
      {
        claim_id: (i + 1) * 10 + 1,
        field: 'affiliation',
        value: affiliation,
        quote: `${name} is part of the ${affiliation}.`,
        url: ROOT_URLS[sourceId]!,
        judge_verdict: 'supported',
        judge_reason: null,
        via_unit: null,
      },
      {
        claim_id: (i + 1) * 10 + 2,
        field: 'expertise',
        value: topics[i % topics.length]!,
        quote: `Research focuses on ${topics[i % topics.length]} and related areas.`,
        url: ROOT_URLS[sourceId]!,
        judge_verdict: i % 3 === 0 ? 'partial' : 'supported',
        judge_reason: i % 3 === 0 ? 'The quote names the area but not this entity.' : null,
        via_unit: null,
      },
      // A person's card also shows the topics of their unit, labelled as the unit's (#44)
      ...(type === 'person'
        ? [
            {
              claim_id: (i + 1) * 10 + 3,
              field: 'unit_expertise',
              value: topics[(i + 2) % topics.length]!,
              quote: `The ${affiliation} works on ${topics[(i + 2) % topics.length]}.`,
              url: ROOT_URLS[sourceId]!,
              judge_verdict: 'supported' as const,
              judge_reason: null,
              via_unit: affiliation,
            },
          ]
        : []),
    ],
  }
}

interface StoredCase {
  data: Case
  readyAt: number
}
const cases = new Map<string, StoredCase>()

function companyFromFile(fileName: string): string {
  const base = fileName
    .replace(/\.pdf$/i, '')
    .replace(/[_-]+/g, ' ')
    .trim()
  return base.replace(/\b\w/g, (c) => c.toUpperCase()) || 'Unnamed company'
}

// [strong, partial, weak] rationale per criterion
const RATIONALES: Record<string, [string, string, string]> = {
  'Research fit': [
    'Several Bern research groups work on the core technology.',
    'Some groups work on related topics, few on the core technology.',
    'Little research in Bern on the core technology.',
  ],
  'Talent pool': [
    'Universities train many graduates in the required fields.',
    'Graduates are available, but in neighbouring fields.',
    'Few local graduates with the required profile.',
  ],
  'Infrastructure & labs': [
    'Labs and platforms the company needs are open to industry partners.',
    'Some shared infrastructure fits; specialised equipment is missing.',
    'The required infrastructure is not available in Bern.',
  ],
  'Industry network': [
    'Strong cluster of companies and hospitals in the same field.',
    'A few potential partners and pilot customers.',
    'Hardly any companies in the same field.',
  ],
  'Market access': [
    'Direct access to clinical partners and the Swiss market.',
    'Market access is possible through partners.',
    'The main market is far from Bern.',
  ],
}

function analyse(c: Case): Case {
  const rand = rng(hash(c.file_name))
  const breakdown = CRITERIA.map((criterion) => {
    const score = Math.round(15 + rand() * 85)
    const [strong, partial, weak] = RATIONALES[criterion]!
    return {
      criterion,
      score,
      rationale: score >= 70 ? strong : score >= 45 ? partial : weak,
    }
  })
  const score = Math.round(breakdown.reduce((sum, b) => sum + b.score, 0) / breakdown.length)
  const industry = INDUSTRIES[Math.floor(rand() * INDUSTRIES.length)] ?? 'MedTech'
  return {
    ...c,
    analysis_status: 'done',
    industry,
    score,
    score_breakdown: breakdown,
    summary:
      `${c.company_name} is a ${industry.toLowerCase()} company looking for a location in ` +
      `Switzerland. It needs access to applied research, qualified engineers and clinical ` +
      `partners to bring its products to market.`,
  }
}

function readCase(id: string): Case {
  const stored = cases.get(id)
  if (!stored) throw new Error('404 Not Found')
  if (stored.data.analysis_status === 'pending' && Date.now() >= stored.readyAt) {
    stored.data = analyse(stored.data)
  }
  return stored.data
}

function seedCase(fileName: string, status: CaseStatus, minutesAgo: number) {
  const id = crypto.randomUUID()
  const base: Case = {
    id,
    company_name: companyFromFile(fileName),
    file_name: fileName,
    uploaded_at: new Date(Date.now() - minutesAgo * 60_000).toISOString(),
    status,
    analysis_status: 'pending',
    industry: null,
    score: null,
    score_breakdown: [],
    summary: null,
  }
  cases.set(id, { data: analyse(base), readyAt: 0 })
}

seedCase('helvetic-glucotech.pdf', 'new', 12)
seedCase('aare-robotics.pdf', 'new', 40)
seedCase('cardiosense-ag.pdf', 'in_review', 180)
seedCase('alpine-bioprint.pdf', 'accepted', 2000)
seedCase('nordsee-logistics.pdf', 'rejected', 300)
seedCase('lakeside-fintech.pdf', 'rejected', 1500)
seedCase('solaris-mining-tools.pdf', 'rejected', 4300)

// --- sources ---

interface StoredSource {
  data: Source
  startedAt: number
  maxPages: number
  maxDepth: number
}
const sources = new Map<string, StoredSource>()

function crawlTree(rootUrl: string, count: number, maxDepth: number, seed: number): CrawledPage[] {
  const rand = rng(seed)
  const origin = new URL(rootUrl).origin
  const pages: CrawledPage[] = [{ url: rootUrl, parent: null, depth: 0, status: 'crawled' }]
  while (pages.length < count) {
    const candidates = pages.filter((p) => p.depth < maxDepth && p.status === 'crawled')
    const parent = candidates[Math.floor(rand() * candidates.length)] ?? pages[0]!
    const roll = rand()
    pages.push({
      url: `${origin}/page-${pages.length}/`,
      parent: parent.url,
      depth: parent.depth + 1,
      status: roll < 0.08 ? 'failed' : roll < 0.18 ? 'skipped' : 'crawled',
    })
  }
  return pages
}

function seedSource(id: string, name: string, pages: number, entities: number, claims: number) {
  const rootUrl = ROOT_URLS[id]!
  sources.set(id, {
    data: {
      id,
      name,
      root_url: rootUrl,
      validated: true,
      status: 'ready',
      pages,
      entities,
      verified_claims: claims,
      last_crawled_at: new Date(Date.now() - 86_400_000).toISOString(),
      discovered: crawlTree(rootUrl, 40, 3, hash(id)),
    },
    startedAt: 0,
    maxPages: pages,
    maxDepth: 3,
  })
}

seedSource('unibe', 'University of Bern web ecosystem', 25, 61, 214)
seedSource('artorg', 'ARTORG Center for Biomedical Engineering Research', 45, 132, 488)
seedSource('dcb', 'Diabetes Center Berne', 30, 74, 259)

function readSource(id: string): Source {
  const stored = sources.get(id)
  if (!stored) throw new Error('404 Not Found')
  const s = stored.data
  if (s.status === 'crawling') {
    const progress = Math.min(1, (Date.now() - stored.startedAt) / CRAWL_MS)
    const shown = Math.max(1, Math.round(progress * Math.min(stored.maxPages, 60)))
    s.discovered = crawlTree(s.root_url, shown, stored.maxDepth, hash(s.id))
    s.pages = s.discovered.filter((p) => p.status === 'crawled').length
    s.entities = Math.round(s.pages * 2.4)
    s.verified_claims = Math.round(s.pages * 7.8)
    if (progress >= 1) {
      s.status = 'ready'
      s.validated = true
      s.last_crawled_at = new Date().toISOString()
    }
  }
  return s
}

export const mockBackend = {
  async listCases(): Promise<Case[]> {
    await wait(250)
    return [...cases.keys()].map((id) => clone(readCase(id)))
  },
  async getCase(id: string): Promise<Case> {
    await wait(150)
    return clone(readCase(id))
  },
  async uploadCase(file: File): Promise<Case> {
    await wait(600)
    const id = crypto.randomUUID()
    const data: Case = {
      id,
      company_name: companyFromFile(file.name),
      file_name: file.name,
      uploaded_at: new Date().toISOString(),
      status: 'new',
      analysis_status: 'pending',
      industry: null,
      score: null,
      score_breakdown: [],
      summary: null,
    }
    cases.set(id, { data, readyAt: Date.now() + ANALYSIS_MS })
    return clone(data)
  },
  async setCaseStatus(id: string, status: CaseStatus): Promise<Case> {
    await wait(150)
    const c = readCase(id)
    c.status = status
    return clone(c)
  },
  async listReferences(id: string, limit: number): Promise<Result[]> {
    await wait(400)
    const c = readCase(id)
    const rand = rng(hash(c.file_name) ^ 0x9e3779b9)
    const why = `Works on topics close to the ${c.industry ?? 'company'} focus of ${c.company_name}.`
    return REFERENCE_POOL.map((_, i) => toResult(i, why, rand()))
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
  },
  // The store keeps the pitches the mock generates, so there is nothing stored to reload
  async getPitch(_id: string): Promise<Pitch | null> {
    return null
  },
  async generatePitch(id: string, entityIds: number[]): Promise<Pitch> {
    await wait(1800)
    const c = readCase(id)
    const refs = entityIds.filter((e) => REFERENCE_POOL[e - 1]).map((e) => toResult(e - 1, '', 0))
    const lines = refs.slice(0, 6).map((r) => `• ${r.name} (${r.affiliations[0]})`)
    return {
      text:
        `Dear ${c.company_name} team,\n\n` +
        `Canton Bern is a strong home for ${c.industry?.toLowerCase() ?? 'your'} companies. ` +
        `Based on your business model, these partners could support you from day one:\n\n` +
        `${lines.join('\n')}\n\n` +
        `We would be happy to introduce you.\nBern Economic Development Agency`,
      entity_ids: entityIds,
      generated_at: new Date().toISOString(),
    }
  },

  // Crude keyword match over the pool; the real agent (PLAN.md 8.10) runs the hybrid search
  async chat(req: ChatRequest): Promise<ChatResponse> {
    await wait(900)
    const words = req.message.toLowerCase().match(/[a-zäöü]{4,}/g) ?? []
    const all = REFERENCE_POOL.map((_, i) => toResult(i, `Matches "${req.message}".`, 0))
    const hits = all.filter((r) =>
      words.some((w) =>
        [r.name, ...r.affiliations, ...r.expertise].join(' ').toLowerCase().includes(w),
      ),
    )
    const rand = rng(hash(req.session_id + req.message))
    const results = (hits.length ? hits : all.filter(() => rand() < 0.2)).slice(0, 6)
    return {
      reply: `Showing ${results.length} results for '${req.message}'.`,
      results: results.map((r, i) => ({ ...r, score: 1 - i * 0.1 })),
      filters: req.filters ?? { source: null, type: null },
      expansion: { en: words, de: [] },
      no_result: results.length === 0,
    }
  },
  async feedback(req: FeedbackRequest): Promise<{ ok: boolean }> {
    await wait(150)
    console.info('[mock] feedback', req)
    return { ok: true }
  },

  async listSources(): Promise<Source[]> {
    await wait(250)
    return [...sources.keys()].map((id) => clone(readSource(id)))
  },
  async getSource(id: string): Promise<Source> {
    await wait(150)
    return clone(readSource(id))
  },
  async addSource(input: NewSource): Promise<Source> {
    await wait(400)
    const url = new URL(input.url)
    const id = url.hostname.replace(/^www\./, '').replace(/[^a-z0-9]+/g, '_')
    const data: Source = {
      id,
      name: input.name || url.hostname,
      root_url: url.href,
      validated: false,
      status: 'crawling',
      pages: 0,
      entities: 0,
      verified_claims: 0,
      last_crawled_at: null,
      discovered: [],
    }
    sources.set(id, {
      data,
      startedAt: Date.now(),
      maxPages: input.max_pages,
      maxDepth: input.max_depth,
    })
    return clone(readSource(id))
  },
}
