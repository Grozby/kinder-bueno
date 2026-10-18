<script setup lang="ts">
// Every crawled page, ranked by its score. Blocked pages drop out of the ranking and are greyed;
// the row actions block, unblock or prioritise a page straight away.
import {
  ArrowDown,
  Ban,
  Building2,
  ChevronsUp,
  FileText,
  FlaskConical,
  FolderKanban,
  LoaderCircle,
  Search,
  TriangleAlert,
  Undo2,
  Users,
} from '@lucide/vue'
import { computed, ref, type Component } from 'vue'

import type { PageKind, ResourcePage, Source } from '@/api'
import ScoreRing from './ScoreRing.vue'
import BaseToggle from './ui/BaseToggle.vue'

const props = defineProps<{
  pages: ResourcePage[]
  sources: Source[]
  loading?: boolean
  error?: string | null
}>()
const emit = defineEmits<{
  open: [id: number]
  block: [page: ResourcePage]
  unblock: [page: ResourcePage]
  prioritise: [page: ResourcePage]
  unprioritise: [page: ResourcePage]
}>()

const source = defineModel<string | null>('source', { default: null })

type SortKey = 'score' | 'verified_claims' | 'entities' | 'judge_supported'

const KINDS: Record<PageKind, { label: string; icon: Component }> = {
  team: { label: 'Team', icon: Users },
  lab: { label: 'Lab / unit', icon: FlaskConical },
  project: { label: 'Project', icon: FolderKanban },
  infrastructure: { label: 'Infrastructure', icon: Building2 },
  other: { label: 'Other', icon: FileText },
}
const SHORT_NAMES: Record<string, string> = { artorg: 'ARTORG', dcb: 'DCB', unibe: 'UniBE' }

const query = ref('')
const kind = ref<PageKind | ''>('')
const showBlocked = ref(true)
const sortKey = ref<SortKey>('score')

const sourceName = (id: string) =>
  SHORT_NAMES[id] ?? props.sources.find((s) => s.id === id)?.name ?? id

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return props.pages.filter(
    (p) =>
      (!source.value || p.source_id === source.value) &&
      (!kind.value || p.kind === kind.value) &&
      (showBlocked.value || !p.blocked_by) &&
      (!q || `${p.title} ${p.url}`.toLowerCase().includes(q)),
  )
})

// Blocked pages keep their score but leave the ranking; they sort to the end
const rows = computed(() =>
  [...filtered.value].sort(
    (a, b) =>
      Number(!!a.blocked_by) - Number(!!b.blocked_by) ||
      (b[sortKey.value] ?? -1) - (a[sortKey.value] ?? -1),
  ),
)
const rank = computed(() => {
  const ranked = filtered.value.filter((p) => !p.blocked_by).sort((a, b) => b.score - a.score)
  return new Map(ranked.map((p, i) => [p.id, i + 1]))
})

const counts = computed(() => ({
  shown: filtered.value.filter((p) => !p.blocked_by).length,
  blocked: filtered.value.filter((p) => p.blocked_by).length,
}))

const COLUMNS: Array<{ key: SortKey; label: string }> = [
  { key: 'score', label: 'Score' },
  { key: 'verified_claims', label: 'Facts' },
  { key: 'entities', label: 'Entities' },
  { key: 'judge_supported', label: 'Judge' },
]
</script>

<template>
  <section class="resources">
    <div class="filters">
      <label class="search">
        <Search :size="16" />
        <input v-model="query" class="input" type="search" placeholder="Filter by title or URL" />
      </label>
      <div class="chips" role="radiogroup" aria-label="Source">
        <button
          role="radio"
          :aria-checked="source === null"
          :class="{ on: source === null }"
          @click="source = null"
        >
          All
        </button>
        <button
          v-for="s in sources"
          :key="s.id"
          role="radio"
          :aria-checked="source === s.id"
          :class="{ on: source === s.id }"
          @click="source = s.id"
        >
          {{ sourceName(s.id) }}
        </button>
      </div>
      <select v-model="kind" class="input kind" aria-label="Page type">
        <option value="">All page types</option>
        <option v-for="(k, key) in KINDS" :key="key" :value="key">{{ k.label }}</option>
      </select>
      <span class="toggle">
        <BaseToggle v-model="showBlocked" label="Show blocked pages" />
        Show blocked
      </span>
      <span class="count muted">
        {{ counts.shown }} ranked<template v-if="counts.blocked">
          · {{ counts.blocked }} blocked</template
        >
      </span>
    </div>

    <p v-if="error" class="load-error">
      <TriangleAlert :size="16" /> The pages could not be loaded: {{ error }}
    </p>

    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th class="rank">#</th>
            <th
              v-for="c in COLUMNS.slice(0, 1)"
              :key="c.key"
              class="sortable score"
              :aria-sort="sortKey === c.key ? 'descending' : 'none'"
            >
              <button @click="sortKey = c.key">
                {{ c.label }} <ArrowDown v-if="sortKey === c.key" :size="13" />
              </button>
            </th>
            <th>Page</th>
            <th>Source</th>
            <th>Type</th>
            <th
              v-for="c in COLUMNS.slice(1)"
              :key="c.key"
              class="sortable num"
              :aria-sort="sortKey === c.key ? 'descending' : 'none'"
            >
              <button @click="sortKey = c.key">
                {{ c.label }} <ArrowDown v-if="sortKey === c.key" :size="13" />
              </button>
            </th>
            <th>Status</th>
            <th class="actions"><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="p in rows"
            :key="p.id"
            :class="{ blocked: p.blocked_by }"
            tabindex="0"
            @click="emit('open', p.id)"
            @keydown.enter="emit('open', p.id)"
          >
            <td class="rank">{{ rank.get(p.id) ?? '–' }}</td>
            <td class="score"><ScoreRing :score="p.score" :size="36" /></td>
            <td class="page">
              <strong>{{ p.title }}</strong>
              <a :href="p.url" target="_blank" rel="noopener" @click.stop>{{ p.url }}</a>
            </td>
            <td>{{ sourceName(p.source_id) }}</td>
            <td class="kind-cell">
              <component :is="KINDS[p.kind].icon" :size="15" /> {{ KINDS[p.kind].label }}
            </td>
            <td class="num">{{ p.verified_claims }}</td>
            <td class="num">{{ p.entities }}</td>
            <td class="num">
              {{ p.judge_supported === null ? '–' : `${Math.round(p.judge_supported * 100)} %` }}
            </td>
            <td class="status">
              <span v-if="p.blocked_by" class="tag" :title="`Matches ${p.blocked_by}`">
                <Ban :size="12" /> Blocked
              </span>
              <span v-else-if="p.status === 'failed'" class="tag tag-bad">Failed</span>
              <span
                v-if="p.prioritised_by && !p.blocked_by"
                class="tag tag-prio"
                :title="`Matches ${p.prioritised_by}`"
              >
                <ChevronsUp :size="12" /> Priority
              </span>
            </td>
            <td class="actions" @click.stop>
              <button
                v-if="p.blocked_by"
                class="icon-btn"
                title="Unblock"
                aria-label="Unblock"
                @click="emit('unblock', p)"
              >
                <Undo2 :size="16" />
              </button>
              <template v-else>
                <button
                  class="icon-btn"
                  :class="{ active: p.prioritised_by }"
                  :title="p.prioritised_by ? 'Remove priority' : 'Prioritise in the next crawl'"
                  :aria-label="p.prioritised_by ? 'Remove priority' : 'Prioritise'"
                  :aria-pressed="!!p.prioritised_by"
                  @click="p.prioritised_by ? emit('unprioritise', p) : emit('prioritise', p)"
                >
                  <ChevronsUp :size="16" />
                </button>
                <button
                  class="icon-btn danger"
                  title="Block this page"
                  aria-label="Block this page"
                  @click="emit('block', p)"
                >
                  <Ban :size="16" />
                </button>
              </template>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-if="loading && !pages.length" class="empty"><LoaderCircle class="spin" :size="20" /></p>
      <p v-else-if="!rows.length" class="empty muted">No pages match these filters.</p>
    </div>
  </section>
</template>

<style scoped>
.resources {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.filters {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.6rem 1rem;
}
.search {
  position: relative;
  display: flex;
  align-items: center;
  width: min(280px, 100%);
}
.search svg {
  position: absolute;
  left: 0.7rem;
  color: var(--text-faint);
}
.search .input {
  padding-left: 2.1rem;
}
.chips {
  display: flex;
  gap: 0.35rem;
}
.chips button {
  height: 32px;
  padding: 0 0.85rem;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
  font-size: 16px;
  cursor: pointer;
}
.chips button:hover:not(.on) {
  background: var(--surface-alt);
}
.chips button.on {
  border-color: var(--text);
  background: var(--text);
  color: #fff;
  font-weight: 600;
}
.chips button:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.kind {
  width: auto;
  height: 32px;
  border-radius: 999px;
  font-size: 16px;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 16px;
}
.count {
  margin-left: auto;
  font-size: 16px;
}

.load-error {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--bad-tint);
  color: var(--bad);
  border-radius: var(--radius);
}

/* Only the table scrolls; its header stays in view */
.table-wrap {
  flex: 1;
  min-height: 0;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
table {
  width: 100%;
  border-collapse: collapse;
  font-size: 16px;
}
th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 0.6rem 0.75rem;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  text-align: left;
  font-size: 14.5px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
  white-space: nowrap;
}
th button {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  padding: 0;
  border: 0;
  background: none;
  font: inherit;
  letter-spacing: inherit;
  text-transform: inherit;
  color: inherit;
  cursor: pointer;
}
th[aria-sort='descending'] button {
  color: var(--text);
}
td {
  padding: 0.55rem 0.75rem;
  border-bottom: 1px solid var(--border-soft);
  vertical-align: middle;
}
tbody tr {
  cursor: pointer;
}
tbody tr:hover {
  background: var(--surface-alt);
}
tbody tr:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
}
.rank {
  width: 2.5rem;
  text-align: right;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  color: var(--text-muted);
}
.score {
  width: 4.5rem;
}
.page {
  max-width: 0;
  width: 40%;
}
.page strong,
.page a {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.page a {
  font-family: var(--mono);
  font-size: 14px;
  color: var(--text-muted);
  text-decoration: none;
}
.page a:hover {
  color: var(--bern-red);
  text-decoration: underline;
}
.kind-cell {
  white-space: nowrap;
  color: var(--text-muted);
}
.kind-cell svg {
  vertical-align: -2px;
}
.num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}
th.num button {
  flex-direction: row-reverse;
}
.status {
  white-space: nowrap;
}
.status .tag + .tag {
  margin-left: 0.3rem;
}
.tag-prio {
  background: var(--text);
  border-color: var(--text);
  color: #fff;
}
.actions {
  width: 5.5rem;
  text-align: right;
  white-space: nowrap;
}
.icon-btn {
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.icon-btn:hover {
  background: var(--border-soft);
  color: var(--text);
}
.icon-btn.active {
  background: var(--text);
  color: #fff;
}
.icon-btn.danger:hover {
  background: var(--bern-red-tint);
  color: var(--bern-red);
}
.icon-btn:focus-visible {
  outline: 2px solid var(--focus);
}

tr.blocked td {
  color: var(--text-faint);
}
tr.blocked .page strong {
  text-decoration: line-through;
  font-weight: 600;
}
tr.blocked .score {
  opacity: 0.45;
}

.empty {
  display: grid;
  place-items: center;
  padding: 2rem;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

@media (max-width: 1100px) {
  .kind-cell,
  th:nth-child(5),
  td:nth-child(5) {
    display: none;
  }
}
</style>
