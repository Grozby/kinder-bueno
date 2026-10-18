<script setup lang="ts">
import { LoaderCircle, TriangleAlert } from '@lucide/vue'
import { computed, ref } from 'vue'

import type { CaseStatus } from '@/api'
import AnalysisOverlay from '@/components/AnalysisOverlay.vue'
import BernBear from '@/components/BernBear.vue'
import CaseCard from '@/components/CaseCard.vue'
import CaseDrawer from '@/components/CaseDrawer.vue'
import UploadDropzone from '@/components/UploadDropzone.vue'
import BaseButton from '@/components/ui/BaseButton.vue'
import BaseOverlay from '@/components/ui/BaseOverlay.vue'
import { feedTheBear } from '@/composables/bernEater'
import { useCasesStore } from '@/stores/cases'

const store = useCasesStore()

const COLUMNS: Array<{ status: CaseStatus; title: string; hint: string }> = [
  { status: 'new', title: 'New', hint: 'Uploaded and scored' },
  { status: 'in_review', title: 'In review', hint: 'Being assessed' },
  { status: 'accepted', title: 'Accepted', hint: 'Ready for a pitch' },
]

const openId = ref<string | null>(null)
const openCase = computed(() => store.cases.find((c) => c.id === openId.value) ?? null)
// The upload whose analysis is shown in the centred pop-up (the last one when several are dropped)
const analysingId = ref<string | null>(null)
const analysingCase = computed(() => store.cases.find((c) => c.id === analysingId.value) ?? null)
const dragging = ref(false)
const overColumn = ref<CaseStatus | null>(null)
const overBear = ref(false)
const notice = ref<{ text: string; undo?: () => void } | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | undefined

const active = computed(() => store.cases.filter((c) => c.status !== 'rejected'))
const scored = computed(() => active.value.filter((c) => c.score !== null))
const avgScore = computed(() =>
  scored.value.length
    ? Math.round(scored.value.reduce((s, c) => s + (c.score ?? 0), 0) / scored.value.length)
    : null,
)

function notify(text: string, undo?: () => void) {
  clearTimeout(noticeTimer)
  notice.value = { text, undo }
  noticeTimer = setTimeout(() => (notice.value = null), 6000)
}

function undo() {
  notice.value?.undo?.()
  notice.value = null
}

async function move(id: string, status: CaseStatus) {
  try {
    await store.move(id, status)
  } catch (e) {
    notify(`Could not move the card: ${(e as Error).message}`)
  }
}

async function reject(id: string, el?: HTMLElement | null) {
  const c = store.cases.find((x) => x.id === id)
  if (!c || c.status === 'rejected') return
  const previous = c.status
  el ??= document.querySelector<HTMLElement>(`[data-case-id="${id}"]`)
  // The bear clones the card synchronously, so the real card can leave the column right away
  const eaten = el ? feedTheBear(el) : Promise.resolve()
  await move(id, 'rejected')
  await eaten
  notify(`${c.company_name} was rejected.`, () => move(id, previous))
}

function rejectFromDrawer() {
  const id = openId.value
  openId.value = null
  // Let the pop-up close first, so the bear can see the card
  if (id) setTimeout(() => reject(id), 250)
}

function openFromRejected(id: string) {
  store.showDiscarded = false
  openId.value = id
}

async function upload(files: File[]) {
  for (const f of files) {
    try {
      const c = await store.upload(f)
      analysingId.value = c.id
    } catch (e) {
      notify(`Upload of ${f.name} failed: ${(e as Error).message}`)
    }
  }
}

function caseIdFrom(e: DragEvent) {
  return e.dataTransfer?.getData('application/x-case-id') || null
}
function acceptsCard(e: DragEvent) {
  return e.dataTransfer?.types.includes('application/x-case-id') ?? false
}

function onColumnDragOver(e: DragEvent, status: CaseStatus) {
  if (!acceptsCard(e)) return
  e.preventDefault()
  overColumn.value = status
}
function onColumnDrop(e: DragEvent, status: CaseStatus) {
  overColumn.value = null
  const id = caseIdFrom(e)
  if (id) move(id, status)
}
function onDragEnd() {
  dragging.value = false
  overColumn.value = null
}
function onBearDragOver(e: DragEvent) {
  if (!acceptsCard(e)) return
  e.preventDefault()
  overBear.value = true
}
function onBearDrop(e: DragEvent) {
  overBear.value = false
  dragging.value = false
  const id = caseIdFrom(e)
  if (id) reject(id)
}
</script>

<template>
  <div class="board-page" @dragstart="dragging = true" @dragend="onDragEnd">
    <section class="intro">
      <div>
        <h1>Settlement pipeline</h1>
        <p class="lead">
          Business models of companies considering a move to the Canton of Bern, scored against the
          Bern research and innovation ecosystem.
        </p>
      </div>
      <UploadDropzone
        class="upload"
        :busy="store.uploading > 0"
        @files="upload"
        @invalid="(names) => notify(`Only PDF files are accepted: ${names.join(', ')}`)"
      />
    </section>

    <div class="toolbar">
      <dl class="kpis">
        <div>
          <dt>Active</dt>
          <dd>{{ active.length }}</dd>
        </div>
        <div>
          <dt>Accepted</dt>
          <dd>{{ store.byStatus.accepted.length }}</dd>
        </div>
        <div>
          <dt>Average fit</dt>
          <dd>{{ avgScore ?? '–' }}</dd>
        </div>
      </dl>
    </div>

    <p v-if="store.error" class="load-error">
      <TriangleAlert :size="16" /> The cases could not be loaded: {{ store.error }}
      <BaseButton size="sm" @click="store.load()">Retry</BaseButton>
    </p>

    <section class="board">
      <div
        v-for="col in COLUMNS"
        :key="col.status"
        class="column"
        :class="[`col-${col.status}`, { over: overColumn === col.status }]"
        @dragover="onColumnDragOver($event, col.status)"
        @dragleave.self="overColumn = null"
        @drop="onColumnDrop($event, col.status)"
      >
        <header>
          <div>
            <h2>{{ col.title }}</h2>
            <p class="hint">{{ col.hint }}</p>
          </div>
          <span class="count">{{ store.byStatus[col.status].length }}</span>
        </header>

        <div class="column-body">
          <TransitionGroup tag="div" name="card" class="cards">
            <CaseCard
              v-for="c in store.byStatus[col.status]"
              :key="c.id"
              :item="c"
              @open="openId = c.id"
              @open-case="(id) => (openId = id)"
              @move="(s) => move(c.id, s)"
            />
          </TransitionGroup>
          <div v-if="!store.byStatus[col.status].length" class="empty">
            <LoaderCircle v-if="store.loading" class="spin" :size="20" />
            <template v-else>Drag cases here</template>
          </div>
        </div>
      </div>
    </section>

    <Transition name="slide-up">
      <div
        v-if="dragging"
        class="bear-target"
        :class="{ over: overBear }"
        @dragover="onBearDragOver"
        @dragleave="overBear = false"
        @drop="onBearDrop"
      >
        <BernBear :open="overBear" class="target-logo" />
        <span>Drop here to reject</span>
      </div>
    </Transition>

    <Transition name="slide-up">
      <div v-if="notice" class="toast" role="status">
        <span>{{ notice.text }}</span>
        <button v-if="notice.undo" @click="undo">Undo</button>
      </div>
    </Transition>

    <BaseOverlay
      :open="store.showDiscarded"
      :title="`Discarded cases (${store.byStatus.rejected.length})`"
      side="center"
      width="1000px"
      @close="store.showDiscarded = false"
    >
      <div v-if="store.byStatus.rejected.length" class="rejected-list">
        <CaseCard
          v-for="c in store.byStatus.rejected"
          :key="c.id"
          :item="c"
          @open="openFromRejected(c.id)"
          @open-case="openFromRejected"
          @move="(s) => move(c.id, s)"
        />
      </div>
      <p v-else class="muted">No discarded cases.</p>
    </BaseOverlay>

    <CaseDrawer
      :item="openCase"
      @close="openId = null"
      @move="(s) => openCase && move(openCase.id, s)"
      @reject="rejectFromDrawer"
      @open="(id) => (openId = id)"
    />

    <AnalysisOverlay
      :item="analysingCase"
      @close="analysingId = null"
      @open="(id) => ((analysingId = null), (openId = id))"
    />
  </div>
</template>

<style scoped>
/* Fills <main> exactly; only the columns scroll. */
.board-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding: 1.5rem clamp(1rem, 2.5vw, 2rem);
}

.intro {
  flex: none;
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  gap: 2rem;
  flex-wrap: wrap;
}
h1 {
  font-size: clamp(26px, 2.6vw, 34px);
}
.lead {
  max-width: 62ch;
  margin-top: 0.35rem;
  font-size: 17px;
  color: var(--text-muted);
}
.upload {
  width: min(440px, 100%);
}

.toolbar {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid var(--border);
}
.kpis {
  display: flex;
  gap: 2rem;
}
.kpis div {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}
.kpis dt {
  font-size: 16px;
  color: var(--text-muted);
}
.kpis dd {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.load-error {
  flex: none;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  background: var(--bad-tint);
  color: var(--bad);
  border-radius: var(--radius);
}
.load-error :deep(.btn) {
  margin-left: auto;
}

.board {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: repeat(3, minmax(320px, 1fr));
  gap: 1.25rem;
  overflow-x: auto;
}
.column {
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: #ececec;
  border-radius: var(--radius-lg);
  transition:
    background-color 0.15s,
    box-shadow 0.15s;
}
/* Stages progress light grey → grey → black */
.col-new {
  --col-color: var(--border-strong);
}
.col-in_review {
  --col-color: var(--text-muted);
}
.col-accepted {
  --col-color: var(--score-strong);
}
.column.over {
  background: var(--bern-red-tint);
  box-shadow: inset 0 0 0 2px var(--bern-red);
}
.column header {
  flex: none;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1.1rem 1.2rem 0.75rem;
}
.column h2 {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  font-size: 19px;
}
.column h2::before {
  content: '';
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--col-color);
}
.hint {
  margin-left: calc(10px + 0.55rem);
  font-size: 15px;
  color: var(--text-muted);
}
.count {
  display: grid;
  place-items: center;
  min-width: 32px;
  height: 28px;
  padding: 0 0.6rem;
  border-radius: 999px;
  background: var(--text);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.column-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  padding: 0.25rem 0.85rem 1rem;
}
.cards {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.empty {
  flex: 1;
  display: grid;
  place-items: center;
  min-height: 140px;
  border: 2px dashed #d4d4d4;
  border-radius: var(--radius-lg);
  color: var(--text-faint);
  font-size: 16px;
}

.rejected-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 0.75rem;
}

.bear-target {
  position: fixed;
  right: 2rem;
  bottom: 2rem;
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  padding: 1rem 1.25rem 0.75rem;
  background: var(--surface);
  border: 2px dashed var(--border-strong);
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
  font-size: 15px;
  font-weight: 600;
  transition: border-color 0.15s;
}
.bear-target.over {
  border-style: solid;
  border-color: var(--bern-red);
  color: var(--bern-red);
}
.target-logo {
  height: 90px;
  width: auto;
  pointer-events: none;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 1.5rem;
  translate: -50% 0;
  z-index: 60;
  display: flex;
  align-items: center;
  gap: 1.25rem;
  max-width: calc(100vw - 2rem);
  padding: 0.75rem 0.75rem 0.75rem 1.25rem;
  background: var(--text);
  color: #fff;
  border-radius: var(--radius);
  box-shadow: var(--shadow-lg);
}
.toast button {
  padding: 0.35rem 0.75rem;
  border: 1px solid rgba(255, 255, 255, 0.5);
  border-radius: var(--radius);
  background: transparent;
  color: #fff;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}
.toast button:hover {
  background: rgba(255, 255, 255, 0.12);
}

.card-move,
.card-enter-active {
  transition:
    transform 0.25s ease-out,
    opacity 0.25s;
}
.card-leave-active {
  transition: opacity 0.12s;
}
.card-enter-from,
.card-leave-to {
  opacity: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition:
    transform 0.2s ease-out,
    opacity 0.2s;
}
.slide-up-enter-from,
.slide-up-leave-to {
  opacity: 0;
  transform: translateY(12px);
}

@media (max-width: 1100px) {
  .lead {
    display: none;
  }
}
@media (max-width: 760px) {
  .board {
    grid-template-columns: repeat(3, 82vw);
    scroll-snap-type: x mandatory;
  }
  .column {
    scroll-snap-align: start;
  }
  .kpis {
    gap: 1rem;
  }
}
</style>
