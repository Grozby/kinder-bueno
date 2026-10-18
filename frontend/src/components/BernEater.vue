<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'

import { BEAR_MOUTH, registerBernEater } from '@/composables/bernEater'
import BernBear from './BernBear.vue'

const visible = ref(false)
const open = ref(false)
const chomping = ref(false)
const satisfied = ref(false)
const flipped = ref(false)
const place = ref<Record<string, string>>({})
const layer = useTemplateRef<HTMLDivElement>('layer')
const bear = useTemplateRef<HTMLDivElement>('bear')

const GAP = 24
const EDGE = 8

// Put the bear beside the card, mouth level with its centre, so it never covers the card.
// Right of the card by default (the bear faces left); mirrored on the left when there is no
// room; along the bottom edge when neither side fits (narrow screens).
function placeBear(rect: DOMRect) {
  const w = Math.min(150, window.innerWidth * 0.3)
  const h = (w * 210) / 120
  const top = Math.min(
    Math.max(rect.top + rect.height / 2 - h * BEAR_MOUTH.y, EDGE),
    window.innerHeight - h - EDGE,
  )
  flipped.value = false
  if (rect.right + GAP + w <= window.innerWidth - EDGE) {
    place.value = { left: `${rect.right + GAP}px`, top: `${top}px` }
  } else if (rect.left - GAP - w >= EDGE) {
    flipped.value = true
    place.value = { left: `${rect.left - GAP - w}px`, top: `${top}px` }
  } else {
    place.value = {
      left: `${(window.innerWidth - w) / 2}px`,
      top: `${window.innerHeight - h - EDGE}px`,
    }
  }
}

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const CRUMB_COLORS = ['#ffd100', '#e30613', '#1d1d1d', '#b8b8b8']

function spawnCrumbs(x: number, y: number) {
  for (let i = 0; i < 16; i++) {
    const crumb = document.createElement('div')
    crumb.className = 'bern-crumb'
    crumb.style.left = `${x}px`
    crumb.style.top = `${y}px`
    crumb.style.background = CRUMB_COLORS[i % CRUMB_COLORS.length]!
    layer.value?.appendChild(crumb)
    const angle = -Math.PI * (0.1 + Math.random() * 0.8)
    const dist = 50 + Math.random() * 90
    crumb
      .animate(
        [
          { transform: 'translate(0, 0) rotate(0deg)', opacity: 1 },
          {
            transform: `translate(${Math.cos(angle) * dist}px, ${Math.sin(angle) * dist + 120}px) rotate(${Math.random() * 720}deg)`,
            opacity: 0,
          },
        ],
        { duration: 700 + Math.random() * 400, easing: 'cubic-bezier(.2,.6,.4,1)' },
      )
      .finished.then(() => crumb.remove())
  }
}

// A new meal cuts the current one short: its card is already in the trash, so its ghost just
// disappears and the bear starts over for the new card. `run` tells a stale meal to stop.
let run = 0
let current: { el: HTMLElement; ghost: HTMLElement; flight?: Animation } | null = null

function clearCurrent() {
  if (!current) return
  current.flight?.cancel()
  current.ghost.remove()
  current.el.style.visibility = ''
  current = null
}

async function eat(el: HTMLElement) {
  if (!layer.value || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

  const id = ++run
  const stale = () => id !== run
  clearCurrent()
  open.value = false
  chomping.value = false
  satisfied.value = false
  if (visible.value) {
    visible.value = false
    await nextTick()
  }

  const rect = el.getBoundingClientRect()
  const ghost = el.cloneNode(true) as HTMLElement
  Object.assign(ghost.style, {
    position: 'fixed',
    left: `${rect.left}px`,
    top: `${rect.top}px`,
    width: `${rect.width}px`,
    height: `${rect.height}px`,
    margin: '0',
    zIndex: '2',
    pointerEvents: 'none',
  })
  layer.value.appendChild(ghost)
  el.style.visibility = 'hidden'
  current = { el, ghost }

  placeBear(rect)
  visible.value = true
  await nextTick()
  await wait(320)
  if (stale()) return
  open.value = true
  await wait(120)
  if (stale()) return

  const bearRect = bear.value!.getBoundingClientRect()
  const mouthX = bearRect.left + bearRect.width * (flipped.value ? 1 - BEAR_MOUTH.x : BEAR_MOUTH.x)
  const mouthY = bearRect.top + bearRect.height * BEAR_MOUTH.y
  const dx = mouthX - (rect.left + rect.width / 2)
  const dy = mouthY - (rect.top + rect.height / 2)

  const flight = ghost.animate(
    [
      { transform: 'translate(0, 0) rotate(0deg) scale(1)' },
      {
        transform: `translate(${dx * 0.55}px, ${dy * 0.55 - 80}px) rotate(-14deg) scale(0.55)`,
        offset: 0.55,
      },
      { transform: `translate(${dx}px, ${dy}px) rotate(10deg) scale(0.04)` },
    ],
    { duration: 750, easing: 'cubic-bezier(.55,0,.8,.4)', fill: 'forwards' },
  )
  current.flight = flight
  try {
    await flight.finished
  } catch {
    return // cancelled by the next meal
  }
  if (stale()) return
  ghost.remove()

  open.value = false
  chomping.value = true
  spawnCrumbs(mouthX, mouthY)
  await wait(500)
  if (stale()) return
  chomping.value = false
  satisfied.value = true
  await wait(900)
  if (stale()) return
  satisfied.value = false
  visible.value = false
  await wait(300)
  if (stale()) return
  el.style.visibility = ''
  current = null
}

onMounted(() => registerBernEater(eat))
onBeforeUnmount(() => registerBernEater(null))
</script>

<template>
  <div ref="layer" class="eater-layer" aria-hidden="true">
    <Transition name="bear">
      <div
        v-if="visible"
        ref="bear"
        class="eater-bear"
        :class="{ chomping, flipped }"
        :style="place"
      >
        <div class="figure">
          <BernBear :open="open" :chomping="chomping" />
        </div>
        <Transition name="bubble">
          <div v-if="satisfied" class="bubble">Merci vöu mau!</div>
        </Transition>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.eater-layer {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 3000;
}

.eater-bear {
  position: fixed;
  width: min(150px, 30vw);
  filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.2));
  z-index: 1;
}
.flipped .figure {
  transform: scaleX(-1);
}
.eater-bear.chomping {
  animation: shake 0.12s linear 4;
}

.bubble {
  position: absolute;
  top: 30%;
  right: 90%;
  padding: 0.4rem 0.75rem;
  border-radius: 4px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  color: var(--text);
  font-weight: 700;
  font-size: 16px;
  white-space: nowrap;
  box-shadow: var(--shadow-lg);
}
.flipped .bubble {
  right: auto;
  left: 90%;
}

.bear-enter-active {
  transition:
    transform 0.32s cubic-bezier(0.2, 1.5, 0.4, 1),
    opacity 0.2s;
}
.bear-leave-active {
  transition:
    transform 0.28s ease-in,
    opacity 0.28s;
}
.bear-enter-from,
.bear-leave-to {
  transform: translateY(24px) scale(0.6);
  opacity: 0;
}

.bubble-enter-active,
.bubble-leave-active {
  transition:
    transform 0.2s cubic-bezier(0.2, 1.6, 0.4, 1),
    opacity 0.2s;
}
.bubble-enter-from,
.bubble-leave-to {
  transform: scale(0.4);
  opacity: 0;
}

@keyframes shake {
  0%,
  100% {
    rotate: 0deg;
  }
  25% {
    rotate: -4deg;
  }
  75% {
    rotate: 4deg;
  }
}
</style>

<style>
.bern-crumb {
  position: fixed;
  width: 7px;
  height: 7px;
  margin: -3px 0 0 -3px;
  border-radius: 2px;
}
</style>
