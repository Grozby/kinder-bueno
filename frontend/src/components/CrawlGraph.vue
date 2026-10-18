<script setup lang="ts">
// Radial tree of a crawl: the start page in the centre, each link depth one ring further out.
import { computed } from 'vue'

import type { CrawledPage } from '@/api'

const props = withDefaults(defineProps<{ pages: CrawledPage[]; compact?: boolean }>(), {
  compact: false,
})

const SIZE = 400
const CENTER = SIZE / 2

interface Node {
  page: CrawledPage
  x: number
  y: number
}

const layout = computed(() => {
  const children = new Map<string | null, CrawledPage[]>()
  for (const p of props.pages) {
    const list = children.get(p.parent) ?? []
    list.push(p)
    children.set(p.parent, list)
  }
  const maxDepth = Math.max(1, ...props.pages.map((p) => p.depth))
  const ring = (CENTER - 18) / maxDepth

  const leaves = new Map<string, number>()
  const countLeaves = (p: CrawledPage): number => {
    const kids = children.get(p.url) ?? []
    const n = kids.length ? kids.reduce((s, k) => s + countLeaves(k), 0) : 1
    leaves.set(p.url, n)
    return n
  }
  const roots = children.get(null) ?? []
  const total = roots.reduce((s, r) => s + countLeaves(r), 0) || 1

  const nodes: Node[] = []
  const edges: Array<{ from: Node; to: Node }> = []
  const place = (p: CrawledPage, start: number, span: number, parent: Node | null) => {
    const angle = start + span / 2
    const r = p.depth * ring
    const node = { page: p, x: CENTER + r * Math.cos(angle), y: CENTER + r * Math.sin(angle) }
    nodes.push(node)
    if (parent) edges.push({ from: parent, to: node })
    let cursor = start
    for (const kid of children.get(p.url) ?? []) {
      const kidSpan = (span * (leaves.get(kid.url) ?? 1)) / (leaves.get(p.url) ?? 1)
      place(kid, cursor, kidSpan, node)
      cursor += kidSpan
    }
  }
  let cursor = -Math.PI / 2
  for (const r of roots) {
    const span = (2 * Math.PI * (leaves.get(r.url) ?? 1)) / total
    place(r, cursor, span, null)
    cursor += span
  }
  return { nodes, edges, rings: Array.from({ length: maxDepth }, (_, i) => (i + 1) * ring) }
})

function edgePath(from: Node, to: Node) {
  // Bend each edge slightly towards the centre, so the tree reads as a constellation
  const mx = (from.x + to.x) / 2
  const my = (from.y + to.y) / 2
  const cx = mx + (CENTER - mx) * 0.15
  const cy = my + (CENTER - my) * 0.15
  return `M${from.x},${from.y} Q${cx},${cy} ${to.x},${to.y}`
}
</script>

<template>
  <svg
    class="graph"
    :class="{ compact }"
    :viewBox="`0 0 ${SIZE} ${SIZE}`"
    role="img"
    aria-label="Crawl graph"
  >
    <circle v-for="r in layout.rings" :key="r" :cx="CENTER" :cy="CENTER" :r="r" class="ring" />
    <path
      v-for="e in layout.edges"
      :key="`${e.from.page.url}>${e.to.page.url}`"
      :d="edgePath(e.from, e.to)"
      class="edge"
    />
    <g
      v-for="n in layout.nodes"
      :key="n.page.url"
      class="node"
      :class="[`s-${n.page.status}`, { root: n.page.parent === null }]"
      :style="{ transformOrigin: `${n.x}px ${n.y}px` }"
    >
      <title>{{ n.page.url }} ({{ n.page.status }})</title>
      <circle :cx="n.x" :cy="n.y" :r="n.page.parent === null ? 9 : compact ? 4 : 5" />
    </g>
  </svg>
</template>

<style scoped>
.graph {
  width: 100%;
  height: auto;
  display: block;
}
.ring {
  fill: none;
  stroke: var(--border);
  stroke-dasharray: 3 4;
}
.edge {
  fill: none;
  stroke: var(--border);
  stroke-width: 1;
}
.node {
  animation: pop 0.3s ease-out;
}
.node circle {
  stroke: var(--surface);
  stroke-width: 1.5;
}
.s-crawled circle {
  fill: var(--text);
}
.s-queued circle {
  fill: var(--text-faint);
  animation: blink 1s ease-in-out infinite;
}
.s-skipped circle {
  fill: var(--border-strong);
}
.s-failed circle {
  fill: var(--surface);
  stroke: var(--bad);
  stroke-width: 2;
}
.root circle {
  fill: var(--bern-red);
}
.compact .edge {
  stroke-width: 0.8;
}

@keyframes pop {
  from {
    transform: scale(0);
    opacity: 0;
  }
}
@keyframes blink {
  50% {
    opacity: 0.35;
  }
}
</style>
