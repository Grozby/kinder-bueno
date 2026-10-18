<script setup lang="ts">
// Asks for the reviewer's name the first time the app is opened in this browser. It is shown
// with their scores and notes; there are no user accounts.
import { nextTick, ref, useTemplateRef, watch } from 'vue'

import { askingName, reviewerName, setReviewerName } from '@/composables/reviewer'
import BernBear from './BernBear.vue'
import BaseButton from './ui/BaseButton.vue'

const draft = ref('')
const input = useTemplateRef<HTMLInputElement>('input')

function save() {
  if (draft.value.trim()) setReviewerName(draft.value)
}

// Cancelling is only possible when changing an existing name; a first visit needs one
function cancel() {
  if (reviewerName.value) askingName.value = false
}

watch(
  askingName,
  async (open) => {
    if (!open) return
    draft.value = reviewerName.value
    await nextTick()
    input.value?.focus()
  },
  { immediate: true },
)
</script>

<template>
  <Teleport to="body">
    <Transition name="prompt" appear>
      <div v-if="askingName" class="backdrop" @mousedown.self="cancel" @keydown.esc="cancel">
        <form
          class="panel"
          role="dialog"
          aria-modal="true"
          aria-labelledby="name-title"
          @submit.prevent="save"
        >
          <BernBear class="logo" />
          <h2 id="name-title">{{ reviewerName ? 'Change your name' : 'Welcome to Bern Fit' }}</h2>
          <p class="muted">
            What is your name? It is shown with the scores and notes you give, so the team knows who
            wrote what. It is kept in this browser only.
          </p>
          <input
            ref="input"
            v-model="draft"
            class="input"
            placeholder="e.g. M. Keller"
            aria-label="Your name"
            autocomplete="name"
          />
          <BaseButton type="submit" variant="primary" :disabled="!draft.trim()"
            >Continue</BaseButton
          >
          <BaseButton v-if="reviewerName" variant="ghost" @click="cancel">Cancel</BaseButton>
        </form>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.backdrop {
  position: fixed;
  inset: 0;
  z-index: 400;
  display: grid;
  place-items: center;
  padding: 1rem;
  background: rgba(20, 20, 20, 0.4);
}
.panel {
  width: min(420px, 100%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.9rem;
  padding: 2rem;
  border-radius: var(--radius-lg);
  background: var(--surface);
  box-shadow: var(--shadow-lg);
  text-align: center;
}
.logo {
  width: 40px;
  height: 70px;
}
h2 {
  font-size: 22px;
}
.muted {
  font-size: 14px;
}
.input {
  text-align: center;
}
.panel :deep(.btn) {
  align-self: stretch;
  justify-content: center;
}

.prompt-enter-active,
.prompt-leave-active {
  transition: opacity 0.2s;
}
.prompt-enter-from,
.prompt-leave-to {
  opacity: 0;
}
</style>
