<script setup lang="ts">
// Centred pop-up for one crawled page: why it scores what it scores, and every verified fact it
// gave, each with its quote. Actions: block it, block pages like it, prioritise it.
import {
  Ban,
  BadgeCheck,
  ChevronsUp,
  CircleHelp,
  ExternalLink,
  FolderX,
  LoaderCircle,
  TriangleAlert,
  Undo2,
} from '@lucide/vue'
import { computed, ref, watch } from 'vue'

import { backend, type PageDetail, type PageFact } from '@/api'
import { useSourcesStore } from '@/stores/sources'
import { timeAgo } from '@/utils/format'
import ScoreRing from './ScoreRing.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseOverlay from './ui/BaseOverlay.vue'

const props = defineProps<{ id: number | null }>()
const emit = defineEmits<{
  close: []
  block: [page: PageDetail]
  blockPattern: [page: PageDetail]
  unblock: [page: PageDetail]
  prioritise: [page: PageDetail]
  unprioritise: [page: PageDetail]
}>()

const store = useSourcesStore()
const page = ref<PageDetail | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

async function fetchPage(id: number) {
  loading.value = !page.value || page.value.id !== id
  error.value = null
  try {
    page.value = await backend.getPage(id)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

watch(
  () => props.id,
  (id) => {
    if (id === null) return
    page.value = null
    fetchPage(id)
  },
)
// A rule change reloads the page list; refresh the open page so its block state follows
watch(
  () => store.pages,
  () => props.id !== null && fetchPage(props.id),
)

// Facts grouped by the entity they are about
const byEntity = computed(() => {
  const groups = new Map<number, { name: string; type: string; facts: PageFact[] }>()
  for (const f of page.value?.facts ?? []) {
    const g = groups.get(f.entity_id) ?? { name: f.entity_name, type: f.entity_type, facts: [] }
    g.facts.push(f)
    groups.set(f.entity_id, g)
  }
  return [...groups.values()]
})
</script>

<template>
  <BaseOverlay
    :open="id !== null"
    side="center"
    width="1100px"
    height="86vh"
    :title="page?.title ?? 'Page'"
    @close="emit('close')"
  >
    <template #header>
      <div v-if="page" class="head">
        <ScoreRing :score="page.score" :size="56" />
        <div class="title">
          <h2>{{ page.title }}</h2>
          <a :href="page.url" target="_blank" rel="noopener" class="url">
            {{ page.url }} <ExternalLink :size="12" />
          </a>
          <div class="tags">
            <span v-if="page.blocked_by" class="tag"><Ban :size="12" /> Blocked</span>
            <span v-if="page.prioritised_by && !page.blocked_by" class="tag tag-prio">
              <ChevronsUp :size="12" /> Priority
            </span>
            <span v-if="page.status === 'failed'" class="tag tag-bad">Fetch failed</span>
            <span class="tag">{{ page.kind }}</span>
            <span v-if="page.crawled_at" class="tag">Crawled {{ timeAgo(page.crawled_at) }}</span>
          </div>
        </div>
        <div class="head-actions">
          <template v-if="page.blocked_by">
            <BaseButton :icon="Undo2" @click="emit('unblock', page)">Unblock</BaseButton>
          </template>
          <template v-else>
            <BaseButton
              :icon="ChevronsUp"
              @click="page.prioritised_by ? emit('unprioritise', page) : emit('prioritise', page)"
            >
              {{ page.prioritised_by ? 'Remove priority' : 'Prioritise' }}
            </BaseButton>
            <BaseButton :icon="FolderX" @click="emit('blockPattern', page)">
              Block similar…
            </BaseButton>
            <BaseButton variant="danger" :icon="Ban" @click="emit('block', page)">Block</BaseButton>
          </template>
        </div>
      </div>
      <h2 v-else>Page</h2>
    </template>

    <p v-if="loading" class="state"><LoaderCircle class="spin" :size="20" /></p>
    <p v-else-if="error" class="state text-error">
      <TriangleAlert :size="16" /> The page could not be loaded: {{ error }}
    </p>

    <div v-else-if="page" class="layout">
      <div class="col">
        <p v-if="page.blocked_by" class="notice">
          <Ban :size="16" />
          <span>
            Hidden from search results and references. It matches the exclude rule
            <code>{{ page.blocked_by }}</code
            >.
          </span>
        </p>

        <h3 class="section-label">Why this score</h3>
        <p class="weights muted">Yield 40 % · Precision 30 % · Verification 20 % · Feedback 10 %</p>
        <ul class="criteria">
          <li v-for="b in page.score_breakdown" :key="b.criterion">
            <ScoreRing :score="b.score" :size="60" />
            <div>
              <strong>{{ b.criterion }}</strong>
              <p>{{ b.rationale }}</p>
            </div>
          </li>
        </ul>

        <h3 class="section-label">In numbers</h3>
        <dl class="numbers">
          <div>
            <dt>Verified facts</dt>
            <dd>{{ page.verified_claims }}</dd>
          </div>
          <div>
            <dt>Entities</dt>
            <dd>{{ page.entities }}</dd>
          </div>
          <div>
            <dt>Judge: supported</dt>
            <dd>
              {{
                page.judge_supported === null ? '–' : `${Math.round(page.judge_supported * 100)} %`
              }}
            </dd>
          </div>
          <div>
            <dt>Dropped facts</dt>
            <dd>{{ page.drop_rate === null ? '–' : `${Math.round(page.drop_rate * 100)} %` }}</dd>
          </div>
          <div>
            <dt>Feedback</dt>
            <dd>{{ page.feedback_up }} ↑ · {{ page.feedback_down }} ↓</dd>
          </div>
        </dl>
      </div>

      <div class="col">
        <h3 class="section-label">
          Facts from this page
          <span class="muted">
            ({{ page.facts.length
            }}<template v-if="page.facts.length < page.verified_claims">
              of {{ page.verified_claims }}</template
            >)
          </span>
        </h3>
        <p v-if="!byEntity.length" class="muted">No verified facts came from this page.</p>
        <section v-for="g in byEntity" :key="g.name" class="entity">
          <h4>
            {{ g.name }} <span class="tag">{{ g.type }}</span>
          </h4>
          <ul>
            <li v-for="f in g.facts" :key="f.claim_id">
              <div class="fact">
                <span class="field">{{ f.field.replace(/_/g, ' ') }}</span>
                <span class="value">{{ f.value }}</span>
                <span
                  class="verdict"
                  :class="f.judge_verdict ?? 'none'"
                  :title="f.judge_verdict ? `Judge: ${f.judge_verdict}` : 'Not judged'"
                >
                  <BadgeCheck v-if="f.judge_verdict === 'supported'" :size="15" />
                  <CircleHelp v-else :size="15" />
                  {{ f.judge_verdict ?? 'not judged' }}
                </span>
              </div>
              <blockquote>“{{ f.quote }}”</blockquote>
            </li>
          </ul>
        </section>
      </div>
    </div>
  </BaseOverlay>
</template>

<style scoped>
.head {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
}
.title {
  flex: 1;
  min-width: 0;
}
.title h2 {
  font-size: 20px;
}
.url {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  max-width: 100%;
  margin-top: 0.15rem;
  font-family: var(--mono);
  font-size: 14.5px;
  color: var(--bern-red);
  text-decoration: none;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.url:hover {
  text-decoration: underline;
}
.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin-top: 0.5rem;
}
.tag-prio {
  background: var(--text);
  border-color: var(--text);
  color: #fff;
}
.head-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 0.5rem;
}

.state {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 0.5rem;
  padding: 2rem;
}

.layout {
  height: 100%;
  display: grid;
  grid-template-columns: 2fr 3fr;
  gap: 2rem;
}
.col {
  min-height: 0;
  overflow-y: auto;
  padding-right: 0.25rem;
}
.section-label {
  margin: 0 0 0.6rem;
}
.col .section-label:not(:first-child) {
  margin-top: 1.5rem;
}

.notice {
  display: flex;
  gap: 0.6rem;
  margin-bottom: 1.25rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  background: var(--surface-alt);
  font-size: 16px;
}
.notice svg {
  flex: none;
  margin-top: 0.15rem;
}
code {
  font-family: var(--mono);
  font-size: 14.5px;
  word-break: break-all;
}

.weights {
  margin: -0.3rem 0 0.75rem;
  font-size: 15px;
}
.criteria {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 0.6rem;
}
.criteria li {
  display: flex;
  align-items: center;
  gap: 0.9rem;
  padding: 0.6rem 0.75rem;
  border-radius: var(--radius-lg);
  background: var(--surface-alt);
}
.criteria strong {
  font-size: 17px;
}
.criteria p {
  font-size: 15.5px;
  color: var(--text-muted);
}

.numbers {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 0.75rem 1rem;
}
.numbers dt {
  font-size: 14.5px;
  color: var(--text-muted);
}
.numbers dd {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.entity + .entity {
  margin-top: 1rem;
}
.entity h4 {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.4rem;
  font-size: 17px;
}
.entity ul {
  list-style: none;
  padding: 0;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
}
.entity li {
  padding: 0.5rem 0.75rem;
}
.entity li + li {
  border-top: 1px solid var(--border-soft);
}
.fact {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  font-size: 16px;
}
.field {
  flex: none;
  min-width: 6.5rem;
  font-size: 14.5px;
  color: var(--text-muted);
  text-transform: capitalize;
}
.value {
  flex: 1;
  min-width: 0;
  font-weight: 600;
}
.verdict {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 14.5px;
  color: var(--text-muted);
}
.verdict.supported {
  color: var(--good);
}
.verdict.partial {
  color: var(--mid);
}
.verdict svg {
  align-self: center;
}
blockquote {
  margin: 0.25rem 0 0 7.1rem;
  font-size: 15px;
  font-style: italic;
  color: var(--text-muted);
}

@media (max-width: 960px) {
  .head {
    flex-wrap: wrap;
  }
  .layout {
    grid-template-columns: 1fr;
    height: auto;
  }
  .col {
    overflow: visible;
  }
  blockquote {
    margin-left: 0;
  }
}
</style>
