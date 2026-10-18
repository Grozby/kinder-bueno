<script setup lang="ts">
// Earlier cases close to this one, with what they share and how the team decided then.
import { ArrowUpRight, Copy } from '@lucide/vue'

import type { CaseStatus, SimilarCase } from '@/api'
import ScoreRing from './ScoreRing.vue'

defineProps<{ cases: SimilarCase[] }>()
const emit = defineEmits<{ open: [id: string] }>()

const STATUS_LABEL: Record<CaseStatus, string> = {
  new: 'New',
  in_review: 'In review',
  accepted: 'Accepted',
  rejected: 'Rejected',
}
</script>

<template>
  <ul class="similar">
    <li v-for="s in cases" :key="s.case_id">
      <button class="row" @click="emit('open', s.case_id)">
        <ScoreRing :score="s.review?.score ?? s.score" :size="44" />
        <span class="text">
          <span class="line">
            <strong>{{ s.company_name }}</strong>
            <span class="tag" :class="{ 'tag-bad': s.status === 'rejected' }">
              {{ STATUS_LABEL[s.status] }}
            </span>
            <span v-if="s.duplicate" class="tag tag-mid"
              ><Copy :size="12" /> Possible duplicate</span
            >
            <span v-else class="muted small">{{ Math.round(s.similarity * 100) }} % similar</span>
          </span>
          <span class="muted small">
            {{ s.shared_references }} shared references<template v-if="s.shared_needs.length">
              · same needs: {{ s.shared_needs.join(', ') }}</template
            >
          </span>
          <span v-if="s.review" class="review small">
            Reviewer {{ s.review.score }}: “{{ s.review.reason }}” — {{ s.review.author }}
          </span>
        </span>
        <ArrowUpRight :size="16" class="go" />
      </button>
    </li>
  </ul>
</template>

<style scoped>
.similar {
  list-style: none;
  padding: 0;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
}
li + li {
  border-top: 1px solid var(--border-soft);
}
.row {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 0.75rem;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
.row:hover {
  background: var(--surface-alt);
}
.row:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: -2px;
}
.text {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.4rem;
  font-size: 16px;
}
.small {
  font-size: 14.5px;
}
.review {
  font-style: italic;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.go {
  flex: none;
  color: var(--text-faint);
}
.row:hover .go {
  color: var(--bern-red);
}
</style>
