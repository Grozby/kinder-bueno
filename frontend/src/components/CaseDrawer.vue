<script setup lang="ts">
// Case details as a centred pop-up: analysis and references on the left,
// chat refinement and sales pitch on the right. Each column scrolls on its own.
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
import { hostOf, timeAgo } from '@/utils/format'
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
    side="center"
    width="1200px"
    height="88vh"
    @close="emit('close')"
  >
    <template #header>
      <div v-if="item" class="head">
        <ScoreRing :score="item.score" :size="56" />
        <div class="head-text">
          <h2>{{ item.company_name }}</h2>
          <p class="meta">
            <span class="tag">{{ STATUS_LABEL[item.status] }}</span>
            <span v-if="item.industry" class="tag">{{ item.industry }}</span>
            <span class="muted"
              >{{ item.file_name }} · uploaded {{ timeAgo(item.uploaded_at) }}</span
            >
          </p>
        </div>
        <div class="actions">
          <BaseButton
            v-if="item.status !== 'rejected'"
            variant="danger"
            :icon="X"
            @click="emit('reject')"
          >
            Reject
          </BaseButton>
          <BaseButton v-else :icon="RotateCcw" @click="emit('move', 'new')">Restore</BaseButton>
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
        </div>
      </div>
    </template>

    <template v-if="item">
      <p v-if="item.analysis_status === 'pending'" class="notice">
        <LoaderCircle class="spin" :size="16" /> The business model is being analysed.
      </p>
      <p v-else-if="item.analysis_status === 'failed'" class="notice score-bad">
        <TriangleAlert :size="16" /> The analysis failed. Please upload the PDF again.
      </p>

      <div v-else class="layout">
        <div class="col col-main">
          <section>
            <h3 class="section-label">Summary</h3>
            <p class="summary">{{ item.summary }}</p>
          </section>

          <section>
            <h3 class="section-label">Score breakdown</h3>
            <ul class="criteria">
              <li v-for="b in item.score_breakdown" :key="b.criterion" :title="b.rationale">
                <ScoreRing :score="b.score" :size="68" />
                <strong>{{ b.criterion }}</strong>
                <span class="rationale">{{ b.rationale }}</span>
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
                <label :title="r.why">
                  <input
                    type="checkbox"
                    :checked="selectedIds.has(r.entity_id)"
                    @change="store.toggleReference(item.id, r.entity_id)"
                  />
                  <span class="rank">{{ refs.indexOf(r) + 1 }}</span>
                  <component :is="TYPE_ICON[r.type]" :size="15" class="type-icon" />
                  <span class="ref-text">
                    <span class="ref-line">
                      <strong>{{ r.name }}</strong>
                      <span v-if="r.affiliations.length" class="muted">
                        · {{ r.affiliations.join(', ') }}
                      </span>
                    </span>
                    <span class="why">{{ r.why }}</span>
                  </span>
                </label>
                <a
                  v-if="r.sources[0]"
                  :href="r.sources[0]"
                  target="_blank"
                  rel="noopener"
                  class="icon-btn"
                  :title="`Source: ${hostOf(r.sources[0])}`"
                >
                  <ExternalLink :size="14" />
                </a>
                <button
                  class="icon-btn"
                  :class="{ on: ratings[r.entity_id] === 'up' }"
                  :disabled="!!ratings[r.entity_id]"
                  title="Good reference"
                  @click="rate(r.entity_id, 'up')"
                >
                  <ThumbsUp :size="14" />
                </button>
                <button
                  class="icon-btn"
                  :class="{ on: ratings[r.entity_id] === 'down' }"
                  :disabled="!!ratings[r.entity_id]"
                  title="Bad reference"
                  @click="rate(r.entity_id, 'down')"
                >
                  <ThumbsDown :size="14" />
                </button>
              </li>
            </ul>
            <button
              v-if="refs.length > DEFAULT_REFERENCES"
              class="more"
              @click="showAll = !showAll"
            >
              <template v-if="showAll">
                Show top {{ DEFAULT_REFERENCES }} only <ChevronUp :size="15" />
              </template>
              <template v-else>
                Show all {{ Math.min(refs.length, MAX_REFERENCES) }} references
                <ChevronDown :size="15" />
              </template>
            </button>
          </section>
        </div>

        <div class="col col-side">
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
            <p v-if="item.status !== 'accepted'" class="muted small">
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
            <p v-else class="muted small">
              Select the references you want, then generate. Only selected references are used.
            </p>
          </section>
        </div>
      </div>
    </template>
  </BaseOverlay>
</template>

<style scoped>
.head {
  display: flex;
  gap: 1rem;
  align-items: center;
}
.head-text {
  flex: 1;
  min-width: 0;
}
.head h2 {
  font-size: 24px;
}
.meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  margin-top: 0.3rem;
  font-size: 13px;
}
.actions {
  display: flex;
  gap: 0.5rem;
  margin-right: 0.5rem;
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

.layout {
  height: 100%;
  display: grid;
  grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
  gap: 2rem;
}
.col {
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.75rem;
  padding-right: 0.5rem;
}
.col-side {
  padding-left: 2rem;
  border-left: 1px solid var(--border);
}

section > .section-label {
  margin-bottom: 0.6rem;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 0.6rem;
}
.summary {
  line-height: 1.65;
}

.criteria {
  list-style: none;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
  gap: 0.75rem;
}
.criteria li {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 0.9rem 0.6rem;
  background: var(--surface-alt);
  border-radius: var(--radius);
  text-align: center;
}
.criteria strong {
  font-size: 13px;
  line-height: 1.25;
}
.rationale {
  font-size: 12px;
  line-height: 1.35;
  color: var(--text-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.refs {
  list-style: none;
  padding: 0;
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.ref {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.4rem 0.6rem 0.4rem 0.75rem;
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
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
}
.ref input {
  flex: none;
  width: 16px;
  height: 16px;
  accent-color: var(--bern-red);
  cursor: pointer;
}
.rank {
  flex: none;
  width: 1.3rem;
  color: var(--text-faint);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.type-icon {
  flex: none;
  color: var(--text-muted);
}
.ref-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.ref-line,
.why {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ref-line {
  font-size: 14px;
}
.why {
  font-size: 12px;
  color: var(--text-muted);
}
.icon-btn {
  flex: none;
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.icon-btn:hover:not(:disabled) {
  background: var(--surface);
  color: var(--text);
}
a.icon-btn:hover {
  color: var(--bern-red);
}
.icon-btn:disabled {
  cursor: default;
  opacity: 0.4;
}
.icon-btn.on {
  opacity: 1;
  background: var(--text);
  color: #fff;
}
.more {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.6rem;
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

@media (max-width: 960px) {
  .layout {
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }
  .col {
    overflow: visible;
    padding-right: 0;
  }
  .col-side {
    padding: 1.75rem 0 0;
    border-left: 0;
    border-top: 1px solid var(--border);
  }
  .head {
    flex-wrap: wrap;
  }
}
</style>
