<script setup lang="ts">
// The claims behind a reference (docs/PLAN.md 9): field, value, quote and source page.
// "Wrong fact" flags one claim; after a click the row says thanks and nothing else changes.
// A person's rows with via_unit are their unit's topics (#44): grouped under the unit, after their own.
import { ExternalLink, Flag } from '@lucide/vue'
import { computed } from 'vue'

import type { Evidence } from '@/api'
import { hostOf } from '@/utils/format'

const props = defineProps<{ evidence: Evidence[]; flagged: number[] }>()
const emit = defineEmits<{ flag: [claimId: number] }>()

// [label, rows]: own evidence first (no label), then one group per unit in the backend's order
const groups = computed(() => {
  const byUnit = new Map<string | null, Evidence[]>([[null, []]])
  for (const e of props.evidence) {
    if (!byUnit.has(e.via_unit)) byUnit.set(e.via_unit, [])
    byUnit.get(e.via_unit)!.push(e)
  }
  return [...byUnit]
    .filter(([, rows]) => rows.length)
    .map(([unit, rows]) => [unit && `Topics of ${unit}`, rows] as const)
})
</script>

<template>
  <p v-if="!evidence.length" class="muted small empty">No evidence rows for this reference.</p>
  <table v-else class="evidence">
    <tbody v-for="[label, rows] in groups" :key="label ?? ''">
      <tr v-if="label" class="group">
        <th colspan="4" scope="rowgroup">{{ label }}</th>
      </tr>
      <tr v-for="e in rows" :key="e.claim_id">
        <th scope="row">{{ e.via_unit ? 'topic' : e.field }}</th>
        <td>
          <div class="claim">
            <span class="value">
              {{ e.value }}
              <span
                v-if="e.judge_verdict === 'partial'"
                class="partial"
                :title="e.judge_reason ?? ''"
              >
                partial
              </span>
            </span>
            <q class="quote">{{ e.quote }}</q>
          </div>
        </td>
        <td class="link">
          <a :href="e.url" target="_blank" rel="noopener" :title="`Source: ${hostOf(e.url)}`">
            {{ hostOf(e.url) }} <ExternalLink :size="12" />
          </a>
        </td>
        <td class="flag">
          <span v-if="flagged.includes(e.claim_id)" class="muted small">Thanks</span>
          <button
            v-else
            class="flag-btn"
            title="Report a wrong fact"
            @click="emit('flag', e.claim_id)"
          >
            <Flag :size="13" /> Wrong fact
          </button>
        </td>
      </tr>
    </tbody>
  </table>
</template>

<style scoped>
.small {
  font-size: 0.875rem;
}
.empty {
  padding: 0.25rem 0 0.25rem 2.9rem;
}
.evidence {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}
.evidence tr + tr,
.evidence tbody + tbody tr:first-child {
  border-top: 1px solid var(--border-soft);
}
.group th {
  padding-top: 0.6rem;
  color: var(--text);
  font-size: 0.8125rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.evidence th,
.evidence td {
  padding: 0.35rem 0.5rem;
  vertical-align: top;
  text-align: left;
}
.evidence th {
  width: 7rem;
  font-weight: 600;
  color: var(--text-muted);
}
.claim {
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.quote {
  color: var(--text-muted);
  font-style: italic;
}
.partial {
  margin-left: 0.3rem;
  padding: 0 0.35rem;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  color: var(--text-muted);
  font-size: 0.8125rem;
  cursor: help;
}
.link,
.flag {
  white-space: nowrap;
}
.link a {
  display: inline-flex;
  align-items: center;
  gap: 0.2rem;
  color: var(--text-muted);
}
.link a:hover {
  color: var(--bern-red);
}
.flag {
  text-align: right;
}
.flag-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.15rem 0.4rem;
  border: 0;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-muted);
  font: inherit;
  cursor: pointer;
}
.flag-btn:hover {
  background: var(--surface);
  color: var(--text);
}
</style>
