<script setup lang="ts">
import { FileText, History, MessageSquare, RotateCcw, TriangleAlert } from '@lucide/vue'
import { computed } from 'vue'

import type { Case, CaseStatus } from '@/api'
import { scoreBand, timeAgo } from '@/utils/format'
import ScoreRing from './ScoreRing.vue'
import BaseButton from './ui/BaseButton.vue'

const props = defineProps<{ item: Case }>()
const emit = defineEmits<{
  open: []
  move: [status: CaseStatus]
  openCase: [id: string]
}>()

const similar = computed(() => props.item.similar_cases?.[0])
const similarLabel = computed(() =>
  similar.value
    ? `${similar.value.duplicate ? 'Possible duplicate of' : 'Similar to'} ${similar.value.company_name} (${STATUS_LABEL[similar.value.status]})`
    : '',
)
const STATUS_LABEL: Record<CaseStatus, string> = {
  new: 'new',
  in_review: 'in review',
  accepted: 'accepted',
  rejected: 'rejected',
}
const pending = computed(() => props.item.analysis_status === 'pending')
const failed = computed(() => props.item.analysis_status === 'failed')

function onDragStart(e: DragEvent) {
  e.dataTransfer?.setData('application/x-case-id', props.item.id)
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}
</script>

<template>
  <article
    class="card"
    :data-case-id="item.id"
    draggable="true"
    tabindex="0"
    @dragstart="onDragStart"
    @click="emit('open')"
    @keydown.enter="emit('open')"
  >
    <header>
      <div class="title">
        <h3>{{ item.company_name }}</h3>
        <p class="file">
          <FileText :size="14" />
          <span class="file-name">{{ item.file_name }}</span>
          <span>· {{ timeAgo(item.uploaded_at) }}</span>
          <span v-if="item.notes_count" class="notes" :title="`${item.notes_count} notes`">
            · <MessageSquare :size="14" /> {{ item.notes_count }}
          </span>
        </p>
      </div>
      <!-- The reviewer's score leads once there is one; the AI score stays visible -->
      <figure
        class="rings"
        :title="item.review ? `Reviewer ${item.review.score} · AI ${item.score}` : 'AI score'"
      >
        <ScoreRing :score="item.review?.score ?? item.score" :size="44" />
        <figcaption v-if="item.review">
          Reviewer<span v-if="item.score !== null"> · AI {{ item.score }}</span>
        </figcaption>
      </figure>
    </header>

    <p v-if="pending" class="state muted">Analysing business model…</p>
    <p v-else-if="failed" class="state text-error"><TriangleAlert :size="14" /> Analysis failed</p>
    <ul v-else class="criteria">
      <li v-for="b in item.score_breakdown.slice(0, 3)" :key="b.criterion">
        <span>{{ b.criterion }}</span>
        <span class="meter">
          <span :class="`fill-${scoreBand(b.score)}`" :style="{ width: `${b.score}%` }" />
        </span>
        <span class="num">{{ b.score }}</span>
      </li>
    </ul>

    <!-- Cards move by drag and drop; only a discarded card needs a button to come back -->
    <footer v-if="item.industry || similar || item.status === 'rejected'">
      <span v-if="item.industry" class="tag">{{ item.industry }}</span>
      <button
        v-if="similar"
        class="similar"
        :class="{ duplicate: similar.duplicate }"
        :title="similarLabel"
        @click.stop="emit('openCase', similar.case_id)"
      >
        <History :size="14" />
        <span>{{ similar.duplicate ? 'Duplicate of' : 'Like' }} {{ similar.company_name }}</span>
      </button>
      <BaseButton
        v-if="item.status === 'rejected'"
        class="restore"
        size="sm"
        :icon="RotateCcw"
        @click.stop="emit('move', 'new')"
      >
        Restore
      </BaseButton>
    </footer>
  </article>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem 1.1rem;
  background: var(--surface);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  cursor: grab;
  transition:
    box-shadow 0.18s,
    transform 0.18s;
}
.card:hover {
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}
.card:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.card:active {
  cursor: grabbing;
}

header {
  display: flex;
  gap: 0.75rem;
  align-items: flex-start;
  justify-content: space-between;
}
.title {
  min-width: 0;
}
h3 {
  font-size: 17px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.15rem;
  font-size: 15px;
  color: var(--text-muted);
  white-space: nowrap;
}
.file svg {
  flex: none;
}
.file-name {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.state {
  display: flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 15px;
}
.criteria {
  list-style: none;
  padding: 0;
  display: grid;
  gap: 0.3rem;
  font-size: 15px;
  color: var(--text-muted);
}
.criteria li {
  display: grid;
  grid-template-columns: 1fr 80px 2ch;
  align-items: center;
  gap: 0.6rem;
}
.meter {
  height: 6px;
  background: var(--surface-alt);
  border-radius: 3px;
  overflow: hidden;
}
.num {
  color: var(--text);
  font-size: 14px;
  font-weight: 600;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.meter span {
  display: block;
  height: 100%;
}
.fill-good {
  background: var(--score-strong);
}
.fill-mid {
  background: var(--score-partial);
}
.fill-bad {
  background: var(--score-weak);
}

.rings {
  flex: none;
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.15rem;
}
.rings figcaption {
  font-size: 13px;
  color: var(--text-muted);
  white-space: nowrap;
}

.notes {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
}

/* One row: the industry tag, then the similar earlier case as a quiet link */
footer {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
  padding-top: 0.75rem;
  border-top: 1px solid var(--border-soft);
}
footer .tag {
  flex: none;
}
.similar {
  min-width: 0;
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  margin-left: auto;
  padding: 0;
  border: 0;
  background: none;
  color: var(--text-muted);
  font: inherit;
  font-size: 14px;
  cursor: pointer;
}
.similar svg {
  flex: none;
}
.similar span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.similar.duplicate {
  color: var(--mid);
}
.similar:hover {
  color: var(--bern-red);
  text-decoration: underline;
}
.similar:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.restore {
  margin-left: auto;
}
</style>
