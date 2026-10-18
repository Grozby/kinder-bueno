<script setup lang="ts">
// Centred pop-up shown while an uploaded business model is analysed. The steps advance on a
// timer and the last one holds until the backend reports the analysis done, then the fit
// score is revealed. Closing it only hides it: the analysis goes on and the card updates.
import { Check, LoaderCircle, TriangleAlert } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, ref, useTemplateRef, watch } from 'vue'

import type { Case } from '@/api'
import { scoreBand } from '@/utils/format'
import BernBear from './BernBear.vue'
import BaseButton from './ui/BaseButton.vue'

const props = defineProps<{ item: Case | null }>()
const emit = defineEmits<{ close: []; open: [id: string] }>()

const STEPS = [
  'Reading the business model',
  'Extracting company profile and needs',
  'Searching UniBE, ARTORG and Diabetes Center Berne',
  'Scoring the fit with Canton Bern',
  'Ranking references',
]
const STEP_MS = 1000
const COUNT_MS = 900
const RING_R = 92
const RING_C = 2 * Math.PI * RING_R

const step = ref(0)
const shownScore = ref(0)
const panel = useTemplateRef<HTMLElement>('panel')
let stepTimer: ReturnType<typeof setInterval> | undefined
let countFrame = 0
let returnFocus: HTMLElement | null = null

const pending = computed(() => props.item?.analysis_status === 'pending')
const failed = computed(() => props.item?.analysis_status === 'failed')
// Done only once the backend is done and every step has had its moment
const done = computed(
  () => !!props.item && !pending.value && !failed.value && step.value >= STEPS.length,
)
const percent = computed(() =>
  done.value
    ? 100
    : Math.round((Math.min(step.value, STEPS.length - 1) + 0.5) * (100 / STEPS.length)),
)
const band = computed(() => scoreBand(props.item?.score ?? 0))
const ringOffset = computed(() => RING_C * (1 - (done.value ? shownScore.value : 0) / 100))

function stop() {
  clearInterval(stepTimer)
  cancelAnimationFrame(countFrame)
}

function countUp(target: number) {
  const start = performance.now()
  const tick = (now: number) => {
    const t = Math.min((now - start) / COUNT_MS, 1)
    shownScore.value = Math.round(target * (1 - (1 - t) ** 3))
    if (t < 1) countFrame = requestAnimationFrame(tick)
  }
  countFrame = requestAnimationFrame(tick)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.item?.id,
  async (id, previous) => {
    stop()
    step.value = 0
    shownScore.value = 0
    if (id && !previous) {
      returnFocus = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', onKey)
    } else if (!id) {
      document.removeEventListener('keydown', onKey)
      returnFocus?.focus?.()
      return
    }
    stepTimer = setInterval(() => {
      // Hold on the last step while the backend is still working
      if (step.value < STEPS.length - 1 || !pending.value) step.value++
      if (step.value >= STEPS.length) clearInterval(stepTimer)
    }, STEP_MS)
    await nextTick()
    panel.value?.focus()
  },
)

watch(done, (isDone) => {
  if (isDone) countUp(props.item?.score ?? 0)
})

onBeforeUnmount(() => {
  stop()
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="analysis">
      <div v-if="item" class="backdrop" @mousedown.self="emit('close')">
        <section
          ref="panel"
          class="panel"
          role="dialog"
          aria-modal="true"
          :aria-label="`Analysis of ${item.file_name}`"
          tabindex="-1"
        >
          <div class="hero" :class="{ done, failed }">
            <svg viewBox="0 0 220 220" aria-hidden="true">
              <circle class="track" cx="110" cy="110" :r="RING_R" />
              <template v-if="!done && !failed">
                <circle class="pulse" cx="110" cy="110" r="70" />
                <circle class="dashes" cx="110" cy="110" r="104" />
                <circle class="arc" cx="110" cy="110" :r="RING_R" />
                <circle class="arc arc-2" cx="110" cy="110" r="80" />
              </template>
              <circle
                v-else-if="done"
                class="result"
                :class="`score-${band}`"
                cx="110"
                cy="110"
                :r="RING_R"
                :stroke-dasharray="RING_C"
                :stroke-dashoffset="ringOffset"
              />
            </svg>
            <div class="center">
              <div v-if="done" class="score">
                <strong>{{ shownScore }}</strong>
                <span>fit score</span>
              </div>
              <TriangleAlert v-else-if="failed" :size="56" class="fail-icon" />
              <BernBear v-else class="emblem" />
            </div>
          </div>

          <p class="eyebrow">
            {{ done ? 'Analysis complete' : failed ? 'Analysis failed' : 'Analysing' }}
          </p>
          <h2>{{ item.company_name }}</h2>
          <p class="file">{{ item.file_name }}</p>

          <ol class="steps" aria-live="polite">
            <li
              v-for="(label, i) in STEPS"
              :key="label"
              :class="{ ok: i < step || done, now: i === step && !done && !failed }"
            >
              <span class="mark">
                <Check v-if="i < step || done" :size="13" :stroke-width="3" />
                <LoaderCircle v-else-if="i === step && !failed" :size="14" class="spin" />
              </span>
              {{ label }}
            </li>
          </ol>

          <div
            v-if="!failed"
            class="progress"
            role="progressbar"
            :aria-valuenow="percent"
            aria-valuemin="0"
            aria-valuemax="100"
          >
            <span :style="{ width: `${percent}%` }" />
          </div>

          <footer>
            <template v-if="done">
              <BaseButton variant="ghost" @click="emit('close')">Back to board</BaseButton>
              <BaseButton variant="primary" @click="emit('open', item.id)">Open case</BaseButton>
            </template>
            <BaseButton v-else variant="ghost" @click="emit('close')">
              {{ failed ? 'Close' : 'Continue in background' }}
            </BaseButton>
          </footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 200;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgba(20, 20, 20, 0.4);
}

.panel {
  width: min(520px, 100%);
  max-height: calc(100vh - 2rem);
  overflow-y: auto;
  padding: 2rem 2.25rem 1.5rem;
  border-radius: var(--radius-lg);
  background: var(--surface);
  color: var(--text);
  text-align: center;
  box-shadow: var(--shadow-lg);
  outline: none;
}

.hero {
  position: relative;
  width: 200px;
  height: 200px;
  margin: 0 auto 1.25rem;
}
/* Only the rings: the emblem is an <svg> too and must keep its own size */
.hero > svg {
  width: 100%;
  height: 100%;
  overflow: visible;
}
.hero circle {
  fill: none;
  transform-origin: 110px 110px;
}
.track {
  stroke: var(--surface-alt);
  stroke-width: 6;
}
.arc {
  stroke: var(--bern-red);
  stroke-width: 6;
  stroke-linecap: round;
  stroke-dasharray: 130 448;
  animation: spin 1.4s linear infinite;
}
.arc-2 {
  stroke: var(--text);
  stroke-width: 2;
  stroke-dasharray: 60 443;
  animation: spin 2.2s linear infinite reverse;
}
.dashes {
  stroke: var(--border-strong);
  stroke-width: 1.5;
  stroke-dasharray: 2 8;
  animation: spin 12s linear infinite;
}
.pulse {
  stroke: var(--bern-red);
  stroke-width: 2;
  animation: pulse 1.8s ease-out infinite;
}
.result {
  stroke-width: 8;
  stroke-linecap: round;
  stroke: currentColor;
  transform: rotate(-90deg);
}

.center {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
}
/* Small enough to sit inside the inner ring (r 80 of 220) with room to breathe */
.emblem {
  width: 40px;
  height: 70px;
  animation: breathe 1.8s ease-in-out infinite;
}
.fail-icon {
  color: var(--bern-red);
}
.score {
  display: grid;
  line-height: 1;
}
.score strong {
  font-size: 64px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.score span {
  margin-top: 0.35rem;
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--bern-red);
}
.done ~ .eyebrow {
  color: var(--text-muted);
}
h2 {
  margin-top: 0.3rem;
  font-size: 24px;
}
.file {
  margin-top: 0.2rem;
  font-family: var(--mono);
  font-size: 12.5px;
  color: var(--text-muted);
}

.steps {
  list-style: none;
  display: grid;
  gap: 0.45rem;
  width: fit-content;
  margin: 1.5rem auto 0;
  padding: 0;
  text-align: left;
  font-size: 14px;
  color: var(--text-faint);
}
.steps li {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  transition: color 0.25s;
}
.steps li.now {
  color: var(--text);
  font-weight: 600;
}
.steps li.ok {
  color: var(--text-muted);
}
.mark {
  display: grid;
  place-items: center;
  flex: none;
  width: 20px;
  height: 20px;
  border-radius: 999px;
  border: 1.5px solid var(--border);
}
.ok .mark {
  border-color: var(--bern-red);
  background: var(--bern-red);
  color: #fff;
}
.now .mark {
  border-color: transparent;
  color: var(--bern-red);
}

.progress {
  height: 4px;
  margin: 1.5rem 0 0;
  border-radius: 999px;
  background: var(--surface-alt);
  overflow: hidden;
}
.progress span {
  display: block;
  height: 100%;
  background: var(--bern-red);
  transition: width 0.8s ease-out;
}

footer {
  display: flex;
  justify-content: center;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

.analysis-enter-active,
.analysis-leave-active {
  transition: opacity 0.25s;
}
.analysis-enter-active .panel {
  transition: transform 0.35s cubic-bezier(0.2, 1.3, 0.4, 1);
}
.analysis-enter-from,
.analysis-leave-to {
  opacity: 0;
}
.analysis-enter-from .panel {
  transform: scale(0.92);
}

@keyframes pulse {
  from {
    transform: scale(0.8);
    opacity: 0.8;
  }
  to {
    transform: scale(1.45);
    opacity: 0;
  }
}
@keyframes breathe {
  50% {
    transform: scale(1.06);
  }
}
</style>
