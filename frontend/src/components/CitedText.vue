<script setup lang="ts">
// Text with claim-id citations (#109): each group like [11258][11259] shows as a small number; a click
// opens the cited facts with their quotes and source pages. A group with an id that is not in
// `evidence` stays as written, so a citation is never hidden.
import { ExternalLink } from '@lucide/vue'
import { computed, onBeforeUnmount, ref } from 'vue'

import type { Evidence } from '@/api'
import { splitCitations } from '@/utils/citations'
import { hostOf } from '@/utils/format'

const props = defineProps<{ text: string; evidence: Map<number, Evidence> }>()

const parts = computed(() =>
  splitCitations(props.text).map((p) => {
    if ('text' in p) return p
    const rows = p.ids.map((id) => props.evidence.get(id))
    return rows.every((e) => e)
      ? { n: p.n, rows: rows as Evidence[] }
      : { text: p.ids.map((id) => `[${id}]`).join('') }
  }),
)

type Place = { left: number; top?: number; bottom?: number }
const open = ref<{ n: number; rows: Evidence[]; place: Place } | null>(null)
let anchor: HTMLElement | null = null

// Below the marker, or above it when the space below is short; null once the marker is off screen
function placeAt(el: HTMLElement): Place | null {
  const r = el.getBoundingClientRect()
  if (r.bottom < 0 || r.top > innerHeight) return null
  const width = Math.min(420, innerWidth - 16)
  const left = Math.max(8, Math.min(r.left, innerWidth - width - 8))
  return innerHeight - r.bottom >= 260
    ? { left, top: r.bottom + 6 }
    : { left, bottom: innerHeight - r.top + 6 }
}

function show(event: MouseEvent, n: number, rows: Evidence[]) {
  if (open.value?.n === n) return close()
  anchor = event.currentTarget as HTMLElement
  const place = placeAt(anchor)
  if (!place) return
  open.value = { n, rows, place }
  addEventListener('keydown', onKey, true) // capture: before the overlay's Escape on document
  addEventListener('scroll', follow, true) // a column scrolls: move with the marker
  addEventListener('resize', follow)
}

function follow() {
  const place = anchor && placeAt(anchor)
  if (!open.value || !place) return close()
  open.value = { ...open.value, place }
}

function close() {
  open.value = null
  anchor = null
  removeEventListener('keydown', onKey, true)
  removeEventListener('scroll', follow, true)
  removeEventListener('resize', follow)
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation() // closes the citation, not the drawer around it
    close()
  }
}

onBeforeUnmount(close)
</script>

<template>
  <span class="cited">
    <template v-for="(p, i) in parts" :key="i">
      <template v-if="'text' in p">{{ p.text }}</template>
      <button
        v-else
        type="button"
        class="cite"
        :class="{ on: open?.n === p.n }"
        :aria-expanded="open?.n === p.n"
        :aria-label="`Source ${p.n}: ${p.rows.length} cited fact${p.rows.length > 1 ? 's' : ''}`"
        @click.stop.prevent="show($event, p.n, p.rows)"
      >
        {{ p.n }}
      </button>
    </template>
  </span>
  <Teleport to="body">
    <template v-if="open">
      <div class="cite-backdrop" @click="close" />
      <div
        class="cite-pop"
        role="dialog"
        :aria-label="`Source ${open.n}`"
        :style="{
          left: `${open.place.left}px`,
          top: open.place.top === undefined ? undefined : `${open.place.top}px`,
          bottom: open.place.bottom === undefined ? undefined : `${open.place.bottom}px`,
        }"
      >
        <div v-for="e in open.rows" :key="e.claim_id" class="cite-row">
          <span class="cite-value">
            <span class="cite-field">{{ e.via_unit ? `topic of ${e.via_unit}` : e.field }}</span>
            {{ e.value }}
          </span>
          <q class="cite-quote">{{ e.quote }}</q>
          <a :href="e.url" target="_blank" rel="noopener">
            {{ hostOf(e.url) }} <ExternalLink :size="12" />
          </a>
        </div>
      </div>
    </template>
  </Teleport>
</template>

<style scoped>
.cite {
  display: inline-grid;
  place-items: center;
  min-width: 1.15rem;
  height: 1.15rem;
  margin: 0 0.1rem;
  padding: 0 0.25rem;
  border: 0;
  border-radius: 999px;
  background: var(--bern-red-tint);
  color: var(--bern-red-dark);
  font: 600 0.7rem/1 var(--font);
  vertical-align: super;
  cursor: pointer;
}
.cite:hover,
.cite.on {
  background: var(--bern-red);
  color: var(--surface);
}
.cite:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 1px;
}
.cite-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
}
.cite-pop {
  position: fixed;
  z-index: 1001;
  width: min(420px, calc(100vw - 16px));
  max-height: 50vh;
  overflow-y: auto;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  white-space: normal;
}
.cite-row {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.5rem 0;
  font-size: 0.875rem;
  line-height: 1.45;
}
.cite-row + .cite-row {
  border-top: 1px solid var(--border-soft);
}
.cite-field {
  margin-right: 0.35rem;
  color: var(--text-muted);
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cite-value {
  font-weight: 600;
}
.cite-quote {
  color: var(--text-muted);
}
.cite-row a {
  align-self: flex-start;
  display: inline-flex;
  gap: 0.25rem;
  align-items: center;
  font-size: 0.8rem;
}
</style>
