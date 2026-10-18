<script setup lang="ts">
import { computed } from 'vue'

import { scoreBand } from '@/utils/format'

const props = withDefaults(defineProps<{ score: number | null; size?: number }>(), { size: 48 })

const R = 20
const CIRCUMFERENCE = 2 * Math.PI * R
const dash = computed(() => CIRCUMFERENCE * ((props.score ?? 0) / 100))
const band = computed(() => (props.score === null ? null : scoreBand(props.score)))
</script>

<template>
  <div
    class="ring"
    :class="band ? `score-${band}` : 'pending'"
    :style="{ width: `${size}px`, height: `${size}px`, fontSize: `${size}px` }"
    :title="score === null ? 'Analysing…' : `Fit score ${score} of 100`"
  >
    <svg viewBox="0 0 48 48">
      <circle cx="24" cy="24" :r="R" class="track" />
      <circle
        v-if="score !== null"
        cx="24"
        cy="24"
        :r="R"
        class="value"
        :stroke-dasharray="`${dash} ${CIRCUMFERENCE}`"
      />
      <circle
        v-else
        cx="24"
        cy="24"
        :r="R"
        class="spinner"
        :stroke-dasharray="`30 ${CIRCUMFERENCE}`"
      />
    </svg>
    <span class="label">{{ score ?? '' }}</span>
  </div>
</template>

<style scoped>
.ring {
  position: relative;
  flex: none;
  display: grid;
  place-items: center;
}
svg {
  position: absolute;
  inset: 0;
  transform: rotate(-90deg);
}
circle {
  fill: none;
  stroke-width: 4;
}
.track {
  stroke: var(--border);
}
.value {
  stroke: currentColor;
  transition: stroke-dasharray 0.6s ease-out;
}
.spinner {
  stroke: var(--text-faint);
  transform-origin: center;
  animation: spin 1s linear infinite;
}
/* The number stays in text ink; only the ring carries the score colour */
.label {
  color: var(--text);
  font-weight: 700;
  font-size: 0.34em;
  font-variant-numeric: tabular-nums;
}
.pending {
  color: var(--text-muted);
}
</style>
