<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, useTemplateRef } from 'vue'

import { BEAR_MOUTH, registerBernEater } from '@/composables/bernEater'
import BernBear from './BernBear.vue'

const visible = ref(false)
const open = ref(false)
const chomping = ref(false)
const satisfied = ref(false)
const layer = useTemplateRef<HTMLDivElement>('layer')
const bear = useTemplateRef<HTMLDivElement>('bear')

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

async function eat(el: HTMLElement) {
  if (!layer.value || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

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

  visible.value = true
  await nextTick()
  await wait(320)
  open.value = true
  await wait(120)

  const bearRect = bear.value!.getBoundingClientRect()
  const mouthX = bearRect.left + bearRect.width * BEAR_MOUTH.x
  const mouthY = bearRect.top + bearRect.height * BEAR_MOUTH.y
  const dx = mouthX - (rect.left + rect.width / 2)
  const dy = mouthY - (rect.top + rect.height / 2)

  await ghost.animate(
    [
      { transform: 'translate(0, 0) rotate(0deg) scale(1)' },
      {
        transform: `translate(${dx * 0.55}px, ${dy * 0.55 - 80}px) rotate(-14deg) scale(0.55)`,
        offset: 0.55,
      },
      { transform: `translate(${dx}px, ${dy}px) rotate(10deg) scale(0.04)` },
    ],
    { duration: 750, easing: 'cubic-bezier(.55,0,.8,.4)', fill: 'forwards' },
  ).finished
  ghost.remove()

  open.value = false
  chomping.value = true
  spawnCrumbs(mouthX, mouthY)
  await wait(500)
  chomping.value = false
  satisfied.value = true
  await wait(900)
  satisfied.value = false
  visible.value = false
  await wait(300)
  el.style.visibility = ''
}

onMounted(() => registerBernEater(eat))
onBeforeUnmount(() => registerBernEater(null))
</script>

<template>
  <div ref="layer" class="eater-layer" aria-hidden="true">
    <Transition name="bear">
      <div v-if="visible" ref="bear" class="eater-bear" :class="{ chomping }">
        <BernBear :open="open" :chomping="chomping" />
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
  left: 50%;
  bottom: 6vh;
  width: min(150px, 30vw);
  translate: -50% 0;
  filter: drop-shadow(0 6px 14px rgba(0, 0, 0, 0.2));
  z-index: 1;
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
  font-size: 14px;
  white-space: nowrap;
  box-shadow: var(--shadow-lg);
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
  transform: translateY(140%) scale(0.6);
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
