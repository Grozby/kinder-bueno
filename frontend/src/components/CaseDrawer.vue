<script setup lang="ts">
import {
  BadgeCheck,
  Building2,
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  ExternalLink,
  FolderKanban,
  LoaderCircle,
  RotateCcw,
  Search,
  Server,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  TriangleAlert,
  User,
  X,
} from '@lucide/vue'
import { computed, ref, watch, type Component } from 'vue'

import type { Case, CaseStatus, EntityType, Rating } from '@/api'
import { DEFAULT_REFERENCES, MAX_REFERENCES, useCasesStore } from '@/stores/cases'
import { hostOf, scoreBand, timeAgo } from '@/utils/format'
import CaseChat from './CaseChat.vue'
import ScoreRing from './ScoreRing.vue'
import BaseButton from './ui/BaseButton.vue'
import BaseOverlay from './ui/BaseOverlay.vue'

const props = defineProps<{ item: Case | null }>()
const emit = defineEmits<{ close: []; move: [status: CaseStatus]; reject: [] }>()

const store = useCasesStore()

const showAll = ref(false)
const refsLoading = ref(false)
const refsError = ref<string | null>(null)
const pitchLoading = ref(false)
const pitchError = ref<string | null>(null)
const copied = ref(false)

const refs = computed(() => (props.item ? (store.references[props.item.id] ?? []) : []))
const selectedIds = computed(() => new Set(props.item ? (store.selected[props.item.id] ?? []) : []))
// Selected references stay visible even when the list is collapsed to the top 10
const visibleRefs = computed(() =>
  showAll.value
    ? refs.value
    : refs.value.filter((r, i) => i < DEFAULT_REFERENCES || selectedIds.value.has(r.entity_id)),
)
const pitch = computed(() => (props.item ? store.pitches[props.item.id] : undefined))
const ratings = computed(() => (props.item ? (store.ratings[props.item.id] ?? {}) : {}))

function rate(entityId: number, rating: Rating) {
  if (props.item) store.rate(props.item.id, props.item.company_name, entityId, rating)
}

const TYPE_ICON: Record<EntityType, Component> = {
  person: User,
  unit: Building2,
  project: FolderKanban,
  infrastructure: Server,
}
const STATUS_LABEL: Record<CaseStatus, string> = {
  new: 'New',
  in_review: 'In review',
  accepted: 'Accepted',
  rejected: 'Rejected',
}

watch(
  () => [props.item?.id, props.item?.analysis_status] as const,
  async ([id, analysis]) => {
    showAll.value = false
    pitchError.value = null
    if (!id || analysis !== 'done') return
    refsLoading.value = true
    refsError.value = null
    try {
      await store.loadReferences(id)
    } catch (e) {
      refsError.value = (e as Error).message
    } finally {
      refsLoading.value = false
    }
  },
  { immediate: true },
)

async function generate() {
  if (!props.item) return
  pitchLoading.value = true
  pitchError.value = null
  try {
    await store.generatePitch(props.item.id)
  } catch (e) {
    pitchError.value = (e as Error).message
  } finally {
    pitchLoading.value = false
  }
}

async function copyPitch() {
  if (!pitch.value) return
  await navigator.clipboard.writeText(pitch.value.text)
  copied.value = true
  setTimeout(() => (copied.value = false), 1500)
}
</script>

<template>
  <BaseOverlay
    :open="item !== null"
    :title="item?.company_name"
    width="640px"
    @close="emit('close')"
  >
    <template #header>
      <div v-if="item" class="head">
        <ScoreRing :score="item.score" :size="60" />
        <div>
          <h2>{{ item.company_name }}</h2>
          <p class="meta">
            <span class="tag">{{ STATUS_LABEL[item.status] }}</span>
            <span v-if="item.industry" class="tag">{{ item.industry }}</span>
            <span class="muted">Uploaded {{ timeAgo(item.uploaded_at) }}</span>
          </p>
        </div>
      </div>
    </template>

    <div v-if="item" class="body">
      <div class="actions">
        <BaseButton
          v-if="item.status === 'new'"
          variant="primary"
          :icon="Search"
          :disabled="item.analysis_status === 'pending'"
          @click="emit('move', 'in_review')"
        >
          Start review
        </BaseButton>
        <BaseButton
          v-if="item.status === 'in_review'"
          variant="primary"
          :icon="BadgeCheck"
          @click="emit('move', 'accepted')"
        >
          Accept
        </BaseButton>
        <BaseButton
          v-if="item.status !== 'rejected'"
          variant="danger"
          :icon="X"
          @click="emit('reject')"
        >
          Reject
        </BaseButton>
        <BaseButton v-else :icon="RotateCcw" @click="emit('move', 'new')">Restore</BaseButton>
      </div>

      <p v-if="item.analysis_status === 'pending'" class="notice">
        <LoaderCircle class="spin" :size="16" /> The business model is being analysed.
      </p>
      <p v-else-if="item.analysis_status === 'failed'" class="notice score-bad">
        <TriangleAlert :size="16" /> The analysis failed. Please upload the PDF again.
      </p>

      <template v-else>
        <section>
          <h3 class="section-label">Summary</h3>
          <p class="summary">{{ item.summary }}</p>
        </section>

        <section>
          <h3 class="section-label">Score breakdown</h3>
          <ul class="breakdown">
            <li v-for="b in item.score_breakdown" :key="b.criterion">
              <div class="row">
                <span>{{ b.criterion }}</span>
                <strong :class="`score-${scoreBand(b.score)}`">{{ b.score }}</strong>
              </div>
              <div class="meter">
                <span :class="`fill-${scoreBand(b.score)}`" :style="{ width: `${b.score}%` }" />
              </div>
              <p class="rationale">{{ b.rationale }}</p>
            </li>
          </ul>
        </section>

        <section>
          <div class="section-head">
            <h3 class="section-label">References</h3>
            <span class="muted small">{{ selectedIds.size }} selected for the pitch</span>
          </div>
          <p v-if="refsLoading" class="notice">
            <LoaderCircle class="spin" :size="16" /> Loading references…
          </p>
          <p v-else-if="refsError" class="notice score-bad">{{ refsError }}</p>
          <ul v-else class="refs">
            <li
              v-for="r in visibleRefs"
              :key="r.entity_id"
              class="ref"
              :class="{ on: selectedIds.has(r.entity_id) }"
            >
              <label>
                <input
                  type="checkbox"
                  :checked="selectedIds.has(r.entity_id)"
                  @change="store.toggleReference(item.id, r.entity_id)"
                />
                <span class="rank">{{ refs.indexOf(r) + 1 }}</span>
                <span class="ref-main">
                  <span class="ref-title">
                    <component :is="TYPE_ICON[r.type]" :size="15" class="type-icon" />
                    <strong>{{ r.name }}</strong>
                  </span>
                  <span v-if="r.affiliations.length" class="affiliation">
                    {{ r.affiliations.join(', ') }}
                  </span>
                  <span class="why">{{ r.why }}</span>
                  <span v-if="r.expertise.length" class="expertise">
                    <span v-for="x in r.expertise.slice(0, 3)" :key="x" class="tag">{{ x }}</span>
                  </span>
                </span>
              </label>
              <div class="ref-foot">
                <div class="links">
                  <a v-for="u in r.sources" :key="u" :href="u" target="_blank" rel="noopener">
                    {{ hostOf(u) }} <ExternalLink :size="12" />
                  </a>
                </div>
                <div class="rating" role="group" aria-label="Rate this reference">
                  <button
                    :class="{ on: ratings[r.entity_id] === 'up' }"
                    :disabled="!!ratings[r.entity_id]"
                    title="Good reference"
                    @click="rate(r.entity_id, 'up')"
                  >
                    <ThumbsUp :size="14" />
                  </button>
                  <button
                    :class="{ on: ratings[r.entity_id] === 'down' }"
                    :disabled="!!ratings[r.entity_id]"
                    title="Bad reference"
                    @click="rate(r.entity_id, 'down')"
                  >
                    <ThumbsDown :size="14" />
                  </button>
                </div>
              </div>
            </li>
          </ul>
          <button v-if="refs.length > DEFAULT_REFERENCES" class="more" @click="showAll = !showAll">
            <template v-if="showAll"
              >Show top {{ DEFAULT_REFERENCES }} only <ChevronUp :size="15"
            /></template>
            <template v-else>
              Show all {{ Math.min(refs.length, MAX_REFERENCES) }} references
              <ChevronDown :size="15" />
            </template>
          </button>
        </section>

        <section>
          <h3 class="section-label">Refine with chat</h3>
          <CaseChat :case-id="item.id" />
        </section>

        <section>
          <div class="section-head">
            <h3 class="section-label">Sales pitch</h3>
            <BaseButton
              v-if="item.status === 'accepted'"
              variant="primary"
              size="sm"
              :icon="Sparkles"
              :loading="pitchLoading"
              :disabled="selectedIds.size === 0"
              @click="generate"
            >
              {{ pitch ? 'Regenerate' : 'Generate pitch' }}
            </BaseButton>
          </div>
          <p v-if="item.status !== 'accepted'" class="muted">
            Accept this company to generate a pitch from the selected references.
          </p>
          <p v-else-if="pitchError" class="notice score-bad">{{ pitchError }}</p>
          <div v-else-if="pitch" class="pitch">
            <div class="pitch-bar">
              <span class="muted small">
                Built from {{ pitch.entity_ids.length }} references ·
                {{ timeAgo(pitch.generated_at) }}
              </span>
              <BaseButton
                size="sm"
                variant="ghost"
                :icon="copied ? Check : Copy"
                @click="copyPitch"
              >
                {{ copied ? 'Copied' : 'Copy' }}
              </BaseButton>
            </div>
            <p class="pitch-text">{{ pitch.text }}</p>
          </div>
          <p v-else class="muted">
            Select the references you want above, then generate. Only selected references are used.
          </p>
        </section>
      </template>
    </div>
  </BaseOverlay>
</template>

<style scoped>
.head {
  display: flex;
  gap: 1rem;
  align-items: center;
}
.head h2 {
  font-size: 22px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.35rem;
  font-size: 13px;
}

.body {
  display: flex;
  flex-direction: column;
  gap: 2rem;
}
.actions {
  display: flex;
  gap: 0.5rem;
}
.notice {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: var(--surface-alt);
  border-radius: var(--radius);
}
.small {
  font-size: 13px;
}

section > .section-label {
  margin-bottom: 0.75rem;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.75rem;
}
.summary {
  line-height: 1.65;
}

.breakdown {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 1rem;
}
.row {
  display: flex;
  justify-content: space-between;
}
.meter {
  height: 6px;
  background: var(--surface-alt);
  border-radius: 3px;
  margin: 0.35rem 0;
  overflow: hidden;
}
.meter span {
  display: block;
  height: 100%;
}
.fill-good {
  background: var(--good);
}
.fill-mid {
  background: var(--mid);
}
.fill-bad {
  background: var(--bad);
}
.rationale {
  font-size: 13px;
  color: var(--text-muted);
}

.refs {
  list-style: none;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.ref {
  padding: 0.75rem 1rem;
  border-left: 3px solid transparent;
}
.ref + .ref {
  border-top: 1px solid var(--border);
}
.ref.on {
  border-left-color: var(--bern-red);
  background: var(--surface-alt);
}
.ref label {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  cursor: pointer;
}
.ref input {
  flex: none;
  width: 17px;
  height: 17px;
  margin-top: 2px;
  accent-color: var(--bern-red);
  cursor: pointer;
}
.rank {
  flex: none;
  width: 1.4rem;
  color: var(--text-faint);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.ref-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.ref-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}
.type-icon {
  flex: none;
  color: var(--text-muted);
}
.affiliation {
  font-size: 13px;
  color: var(--text-muted);
}
.why {
  font-size: 13px;
  margin-top: 0.25rem;
}
.expertise {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
  margin-top: 0.4rem;
}
.ref-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0.35rem 0 0 calc(17px + 1.4rem + 1.5rem);
}
.links {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
}
.rating {
  display: flex;
  gap: 0.25rem;
}
.rating button {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  color: var(--text-muted);
  cursor: pointer;
}
.rating button:hover:not(:disabled) {
  border-color: var(--text);
  color: var(--text);
}
.rating button:disabled {
  cursor: default;
  opacity: 0.45;
}
.rating button.on {
  opacity: 1;
  background: var(--text);
  border-color: var(--text);
  color: #fff;
}
.links a {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  font-size: 13px;
  color: var(--bern-red);
  text-decoration: none;
}
.links a:hover {
  text-decoration: underline;
}
.more {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.75rem;
  padding: 0;
  border: 0;
  background: none;
  color: var(--bern-red);
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.more:hover {
  text-decoration: underline;
}

.pitch {
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.pitch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.5rem 0.4rem 1rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface-alt);
}
.pitch-text {
  padding: 1rem;
  white-space: pre-wrap;
  line-height: 1.65;
}
</style>
