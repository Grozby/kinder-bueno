// In-memory stand-in for the backend, so the UI can be built and demoed before the API exists.
// All names are placeholders ("Muster" = Swiss "example"); none of this is real data.
import type {
  Case,
  CaseChatTurn,
  CaseFeedback,
  CaseStatus,
  ChatRequest,
  ChatResponse,
  CrawledPage,
  CrawlRules,
  EntityType,
  FeedbackRequest,
  NewSource,
  PageDetail,
  PageFact,
  PageKind,
  PageStatus,
  Pitch,
  ResourcePage,
  Result,
  RuleKind,
  Selection,
  Source,
} from './types'
import { isValidPattern, matches } from '@/utils/patterns'

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

// --- resources: crawl rules and pages ---

// The rules from config/sources.yaml, so the demo blocks and prioritises with real patterns
const rules = new Map<string, CrawlRules>([
  [
    'artorg',
    {
      allow_hosts: ['www.artorg.unibe.ch'],
      include_patterns: ['index_eng\\.html$'],
      exclude_patterns: ['/news_and_events/', '/jobs/', '/publications/', '/teaching/'],
      priority_patterns: [
        '^https://www\\.artorg\\.unibe\\.ch/research/[a-z0-9_]+/index_eng\\.html$',
        '^https://www\\.artorg\\.unibe\\.ch/research/[a-z0-9_]+/group_members/index_eng\\.html$',
      ],
      changed_at: null,
    },
  ],
  [
    'dcb',
    {
      allow_hosts: ['www.dcberne.com'],
      include_patterns: ['^https://www\\.dcberne\\.com/en/'],
      exclude_patterns: ['/wp-json/', '/career/', '/legal-notice/', '/news/'],
      priority_patterns: ['/en/project/', '/innovation/$'],
      changed_at: null,
    },
  ],
  [
    'unibe',
    {
      allow_hosts: ['www.dbmr.unibe.ch', 'www.cvrc.unibe.ch', 'www.sitem.unibe.ch'],
      include_patterns: ['index_eng\\.html$'],
      exclude_patterns: ['/news', '/jobs/', '/events/'],
      priority_patterns: ['/research_programs/[a-z0-9_]+/index_eng\\.html$'],
      changed_at: null,
    },
  ],
])

// [path, title, kind] per source; the hosts come from the allow list
const PAGE_SEEDS: Record<string, Array<[string, string, PageKind]>> = {
  artorg: [
    ...[
      'surgical_robotics',
      'hearing_research',
      'cardiovascular',
      'medical_imaging',
      'ai_health',
      'gait_lab',
    ].flatMap((lab): Array<[string, string, PageKind]> => {
      const name = lab.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
      return [
        [`https://www.artorg.unibe.ch/research/${lab}/index_eng.html`, `${name} Lab`, 'lab'],
        [
          `https://www.artorg.unibe.ch/research/${lab}/group_members/index_eng.html`,
          `${name} Lab: group members`,
          'team',
        ],
      ]
    }),
    [
      'https://www.artorg.unibe.ch/services/prototyping/index_eng.html',
      'Prototyping workshop',
      'infrastructure',
    ],
    [
      'https://www.artorg.unibe.ch/services/biomech_testing/index_eng.html',
      'Biomechanics testing',
      'infrastructure',
    ],
    ['https://www.artorg.unibe.ch/research/index_eng.html', 'Research overview', 'other'],
    ['https://www.artorg.unibe.ch/about_us/index_eng.html', 'About us', 'other'],
    ['https://www.artorg.unibe.ch/news_and_events/index_eng.html', 'News and events', 'other'],
  ],
  dcb: [
    ['https://www.dcberne.com/en/team/', 'Team', 'team'],
    [
      'https://www.dcberne.com/en/project/smart-insulin-patch/',
      'Project: Smart insulin patch',
      'project',
    ],
    [
      'https://www.dcberne.com/en/project/closed-loop-control/',
      'Project: Closed-loop glucose control',
      'project',
    ],
    [
      'https://www.dcberne.com/en/project/ai-nutrition-coach/',
      'Project: AI nutrition coach',
      'project',
    ],
    [
      'https://www.dcberne.com/en/project/sensor-validation/',
      'Project: Sensor validation',
      'project',
    ],
    ['https://www.dcberne.com/en/focus-areas/', 'Focus areas', 'lab'],
    ['https://www.dcberne.com/en/offering/', 'Offering for start-ups', 'infrastructure'],
    ['https://www.dcberne.com/en/innovation/', 'Innovation', 'other'],
    ['https://www.dcberne.com/en/partners-network/', 'Partners network', 'other'],
    ['https://www.dcberne.com/en/contact/', 'Contact', 'other'],
  ],
  unibe: [
    ...['muster_lab', 'imaging_lab', 'metabolism_lab', 'cardio_lab'].flatMap(
      (lab): Array<[string, string, PageKind]> => {
        const name = lab.replace(/_lab$/, '').replace(/\b\w/g, (c) => c.toUpperCase())
        return [
          [
            `https://www.dbmr.unibe.ch/research/research_programs/${lab}/index_eng.html`,
            `${name} Lab`,
            'lab',
          ],
          [
            `https://www.dbmr.unibe.ch/research/research_programs/${lab}/team/index_eng.html`,
            `${name} Lab: team`,
            'team',
          ],
        ]
      },
    ),
    ['https://www.cvrc.unibe.ch/index_eng.html', 'Cardiovascular Research Cluster', 'lab'],
    ['https://www.sitem.unibe.ch/index_eng.html', 'sitem-insel', 'infrastructure'],
    [
      'https://www.sitem.unibe.ch/translational_imaging/index_eng.html',
      'Translational imaging center',
      'infrastructure',
    ],
    [
      'https://www.dbmr.unibe.ch/research/research_programs/index_eng.html',
      'Research programmes',
      'other',
    ],
  ],
}

// Facts and entities a page of this kind typically yields: [min facts, max facts]
const YIELD: Record<PageKind, [number, number]> = {
  team: [22, 46],
  lab: [10, 26],
  project: [6, 16],
  infrastructure: [4, 11],
  other: [0, 4],
}

interface StoredPage {
  id: number
  source_id: string
  url: string
  title: string
  kind: PageKind
  status: PageStatus
  verified_claims: number
  entities: number
  judge_supported: number | null
  drop_rate: number | null
  feedback_up: number
  feedback_down: number
}

const pages: StoredPage[] = Object.entries(PAGE_SEEDS)
  .flatMap(([sourceId, seeds]) =>
    seeds.map(([url, title, kind]) => {
      const rand = rng(hash(url))
      const [lo, hi] = YIELD[kind]
      const claims = Math.round(lo + rand() * (hi - lo))
      return {
        id: 0,
        source_id: sourceId,
        url,
        title,
        kind,
        status: (rand() < 0.06 ? 'failed' : 'crawled') as PageStatus,
        verified_claims: claims,
        entities: Math.max(claims ? 1 : 0, Math.round(claims / (kind === 'team' ? 2.6 : 4))),
        judge_supported: claims ? 0.62 + rand() * 0.38 : null,
        drop_rate: claims ? rand() * 0.32 : null,
        feedback_up: Math.floor(rand() * (claims / 6)),
        feedback_down: Math.floor(rand() * 2.4),
      }
    }),
  )
  .map((p, i) => ({ ...p, id: i + 1 }))

const pct = (share: number) => `${Math.round(share * 100)} %`

function toResourcePage(p: StoredPage): ResourcePage {
  const r = rules.get(p.source_id)
  const failed = p.status === 'failed'
  const claims = failed ? 0 : p.verified_claims
  const yieldScore = Math.min(100, Math.round((claims / 40) * 100))
  const precision = !failed && p.judge_supported !== null ? Math.round(p.judge_supported * 100) : 0
  const survival = !failed && p.drop_rate !== null ? Math.round((1 - p.drop_rate) * 100) : 0
  const votes = p.feedback_up + p.feedback_down
  const feedback = Math.round(((p.feedback_up + 1) / (votes + 2)) * 100)
  return {
    id: p.id,
    source_id: p.source_id,
    url: p.url,
    title: p.title,
    kind: p.kind,
    status: p.status,
    score: Math.round(0.4 * yieldScore + 0.3 * precision + 0.2 * survival + 0.1 * feedback),
    score_breakdown: [
      {
        criterion: 'Yield',
        score: yieldScore,
        rationale: failed
          ? 'The page could not be fetched.'
          : `${claims} verified facts about ${p.entities} people, units or projects.`,
      },
      {
        criterion: 'Precision',
        score: precision,
        rationale:
          p.judge_supported === null || failed
            ? 'No facts to judge.'
            : `The judge found ${pct(p.judge_supported)} of the facts fully supported by their quote.`,
      },
      {
        criterion: 'Verification',
        score: survival,
        rationale:
          p.drop_rate === null || failed
            ? 'Nothing was extracted.'
            : `${pct(p.drop_rate)} of the extracted facts were dropped: their quote was not on the page.`,
      },
      {
        criterion: 'Feedback',
        score: feedback,
        rationale: votes
          ? `${p.feedback_up} up and ${p.feedback_down} down on results that cite this page.`
          : 'No feedback yet.',
      },
    ],
    entities: failed ? 0 : p.entities,
    verified_claims: claims,
    judge_supported: failed ? null : p.judge_supported,
    drop_rate: failed ? null : p.drop_rate,
    feedback_up: p.feedback_up,
    feedback_down: p.feedback_down,
    crawled_at: sources.get(p.source_id)?.data.last_crawled_at ?? null,
    blocked_by: r?.exclude_patterns.find((x) => matches(x, p.url)) ?? null,
    prioritised_by: r?.priority_patterns.find((x) => matches(x, p.url)) ?? null,
  }
}

const FACT_FIELDS: Record<EntityType, string[]> = {
  person: ['role', 'expertise', 'member_of', 'contact'],
  unit: ['expertise', 'part_of', 'project'],
  project: ['expertise', 'partner', 'funding'],
  infrastructure: ['service', 'part_of'],
}

function pageFacts(p: StoredPage): PageFact[] {
  if (p.status === 'failed' || !p.verified_claims) return []
  const rand = rng(hash(p.url) ^ 0x5bd1e995)
  const pool = REFERENCE_POOL.map((e, i) => ({ e, i })).filter(({ e }) => e[3] === p.source_id)
  const topics = EXPERTISE[p.source_id]!
  const facts: PageFact[] = []
  for (let n = 0; n < Math.min(p.verified_claims, 14); n++) {
    const { e, i } = pool[Math.floor(rand() * Math.min(pool.length, p.entities || 1))]!
    const [type, name, affiliation] = e
    const field = FACT_FIELDS[type][Math.floor(rand() * FACT_FIELDS[type].length)]!
    const topic = topics[Math.floor(rand() * topics.length)]!
    const value =
      field === 'role'
        ? 'Group leader'
        : field === 'member_of' || field === 'part_of'
          ? affiliation
          : field === 'contact'
            ? `${name.split(' ').pop()!.toLowerCase()}@example.unibe.ch`
            : topic
    facts.push({
      claim_id: p.id * 100 + n,
      entity_id: i + 1,
      entity_name: name,
      entity_type: type,
      field,
      value,
      quote:
        field === 'role'
          ? `${name}, ${value}`
          : field === 'contact'
            ? `${name} · ${value}`
            : `${name} … ${value === topic ? `works on ${topic}` : `is part of the ${value}`}.`,
      judge_verdict: rand() < 0.82 ? 'supported' : 'partial',
    })
  }
  return facts
}

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

// Case drawer state (#81), kept per case like the backend keeps it in the DB
const selections = new Map<string, number[]>()
const addedRefs = new Map<string, Result[]>()
const chatTurns = new Map<string, CaseChatTurn[]>()
const caseFeedback = new Map<string, CaseFeedback>()
const caseOf = (sessionId: string) => (sessionId.startsWith('case-') ? sessionId.slice(5) : null)

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
      .concat(addedRefs.get(id) ?? [])
      .filter((r, i, all) => all.findIndex((x) => x.entity_id === r.entity_id) === i)
  },
  async getSelection(id: string): Promise<Selection> {
    const stored = selections.get(id)
    if (stored) return { entity_ids: [...stored] }
    const refs = await mockBackend.listReferences(id, 10)
    return { entity_ids: refs.map((r) => r.entity_id) }
  },
  async setSelection(id: string, entityIds: number[]): Promise<Selection> {
    await wait(100)
    selections.set(id, [...new Set(entityIds)])
    return { entity_ids: [...selections.get(id)!] }
  },
  async addReference(id: string, entityId: number): Promise<Result> {
    await wait(150)
    if (!REFERENCE_POOL[entityId - 1]) throw new Error('404 Not Found')
    const fromChat = (chatTurns.get(id) ?? [])
      .flatMap((t) => t.response.results)
      .reverse()
      .find((r) => r.entity_id === entityId)
    const ref = { ...(fromChat ?? toResult(entityId - 1, '', 0)), added: true }
    const list = (addedRefs.get(id) ?? []).filter((r) => r.entity_id !== entityId)
    addedRefs.set(id, [...list, ref])
    return clone(ref)
  },
  async removeReference(id: string, entityId: number): Promise<Selection> {
    await wait(150)
    addedRefs.set(id, (addedRefs.get(id) ?? []).filter((r) => r.entity_id !== entityId))
    const stored = selections.get(id)
    if (stored) selections.set(id, stored.filter((e) => e !== entityId))
    return mockBackend.getSelection(id)
  },
  async getCaseChat(id: string): Promise<CaseChatTurn[]> {
    await wait(150)
    return clone(chatTurns.get(id) ?? [])
  },
  async getCaseFeedback(id: string): Promise<CaseFeedback> {
    await wait(100)
    return clone(caseFeedback.get(id) ?? { ratings: {}, flagged: [] })
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
    const response: ChatResponse = {
      reply: `Showing ${results.length} results for '${req.message}'.`,
      results: results.map((r, i) => ({ ...r, score: 1 - i * 0.1 })),
      filters: req.filters ?? { source: null, type: null },
      expansion: { en: words, de: [] },
      no_result: results.length === 0,
    }
    const caseId = caseOf(req.session_id)
    if (caseId) {
      const turn = { message: req.message, response, created_at: new Date().toISOString() }
      chatTurns.set(caseId, [...(chatTurns.get(caseId) ?? []), clone(turn)])
    }
    return response
  },
  async feedback(req: FeedbackRequest): Promise<{ ok: boolean }> {
    await wait(150)
    console.info('[mock] feedback', req)
    const caseId = caseOf(req.session_id)
    if (caseId) {
      const stored = caseFeedback.get(caseId) ?? { ratings: {}, flagged: [] }
      if (req.rating === 'wrong_fact' && req.claim_id != null) stored.flagged.push(req.claim_id)
      else if (req.rating !== 'wrong_fact') stored.ratings[req.entity_id] = req.rating
      caseFeedback.set(caseId, stored)
    }
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
  async recrawlSource(id: string): Promise<Source> {
    await wait(300)
    const stored = sources.get(id)
    if (!stored) throw new Error('404 Not Found')
    stored.data.status = 'crawling'
    stored.startedAt = Date.now()
    return clone(readSource(id))
  },
  async getRules(id: string): Promise<CrawlRules> {
    await wait(150)
    const r = rules.get(id)
    if (!r)
      return {
        allow_hosts: [],
        include_patterns: [],
        exclude_patterns: [],
        priority_patterns: [],
        changed_at: null,
      }
    return clone(r)
  },
  async setRules(id: string, next: Record<RuleKind, string[]>): Promise<CrawlRules> {
    await wait(250)
    for (const pattern of [
      ...next.include_patterns,
      ...next.exclude_patterns,
      ...next.priority_patterns,
    ]) {
      if (!isValidPattern(pattern)) throw new Error(`422 Invalid pattern: ${pattern}`)
    }
    const saved: CrawlRules = { ...clone(next), changed_at: new Date().toISOString() }
    rules.set(id, saved)
    return clone(saved)
  },

  async listPages(): Promise<ResourcePage[]> {
    await wait(300)
    return pages.map(toResourcePage)
  },
  async getPage(id: number): Promise<PageDetail> {
    await wait(200)
    const p = pages.find((x) => x.id === id)
    if (!p) throw new Error('404 Not Found')
    return { ...toResourcePage(p), facts: pageFacts(p) }
  },
}
