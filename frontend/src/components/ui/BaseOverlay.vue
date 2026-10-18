<script setup lang="ts">
// A panel over the page: slides in from the right (`side="right"`) or opens as a centred dialog.
// Closes on Esc and on a backdrop click, and gives focus back to where it was on close.
// With `height`, a centred dialog keeps that height and its content handles its own scrolling.
import { X } from '@lucide/vue'
import { nextTick, onBeforeUnmount, useTemplateRef, watch } from 'vue'

import { trapFocus } from '@/composables/focusTrap'

const props = withDefaults(
  defineProps<{
    open: boolean
    side?: 'right' | 'center'
    title?: string
    width?: string
    height?: string
  }>(),
  { side: 'right', width: '600px', height: undefined },
)
const emit = defineEmits<{ close: [] }>()

const panel = useTemplateRef<HTMLElement>('panel')
let returnFocus: HTMLElement | null = null

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      returnFocus = document.activeElement as HTMLElement | null
      document.addEventListener('keydown', onKey)
      document.body.style.overflow = 'hidden'
      await nextTick()
      panel.value?.focus()
    } else {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = ''
      returnFocus?.focus?.()
    }
  },
)

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey)
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <Transition :name="`overlay-${side}`">
      <div v-if="open" class="backdrop" :class="`side-${side}`" @mousedown.self="emit('close')">
        <section
          ref="panel"
          class="panel"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          tabindex="-1"
          :class="{ fixed: height }"
          @keydown="trapFocus($event, panel)"
          :style="{ '--panel-width': width, '--panel-height': height }"
        >
          <header class="panel-head">
            <div class="panel-title">
              <slot name="header">
                <h2>{{ title }}</h2>
              </slot>
            </div>
            <button class="close" aria-label="Close" @click="emit('close')">
              <X :size="20" />
            </button>
          </header>
          <div class="panel-body">
            <slot />
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(20, 20, 20, 0.4);
  display: flex;
}
.side-right {
  justify-content: flex-end;
}
.side-center {
  align-items: center;
  justify-content: center;
  padding: 1rem;
}

.panel {
  display: flex;
  flex-direction: column;
  width: min(var(--panel-width), 100vw);
  background: var(--surface);
  outline: none;
}
.side-right .panel {
  height: 100%;
  border-left: 1px solid var(--border);
}
.side-center .panel.fixed {
  height: min(var(--panel-height), calc(100vh - 2rem));
}
.panel.fixed .panel-body {
  overflow: hidden;
}
.side-center .panel {
  max-height: calc(100vh - 2rem);
  overflow: hidden;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}

.panel-head {
  display: flex;
  align-items: flex-start;
  gap: 1rem;
  padding: 1.25rem 1.5rem;
  border-bottom: 1px solid var(--border-soft);
}
.panel-title {
  flex: 1;
  min-width: 0;
}
.panel-title h2 {
  font-size: 1.25rem;
}
.close {
  flex: none;
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.close:hover {
  background: var(--surface-alt);
  color: var(--text);
}
.close:focus-visible {
  outline: 2px solid var(--focus);
}
.panel-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.overlay-right-enter-active,
.overlay-right-leave-active,
.overlay-center-enter-active,
.overlay-center-leave-active {
  transition: background-color 0.2s;
}
.overlay-right-enter-active .panel,
.overlay-right-leave-active .panel,
.overlay-center-enter-active .panel,
.overlay-center-leave-active .panel {
  transition:
    transform 0.22s ease-out,
    opacity 0.2s;
}
.overlay-right-enter-from,
.overlay-right-leave-to,
.overlay-center-enter-from,
.overlay-center-leave-to {
  background-color: transparent;
}
.overlay-right-enter-from .panel,
.overlay-right-leave-to .panel {
  transform: translateX(100%);
}
.overlay-center-enter-from .panel,
.overlay-center-leave-to .panel {
  transform: translateY(8px);
  opacity: 0;
}
</style>
