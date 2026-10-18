<script setup lang="ts">
// The reviewer's side of a case: their own 0-100 score with a required reason, kept next to the
// AI score, and a timeline of notes. Notes are internal; they never go into the sales pitch.
import { LoaderCircle, Pencil, Send, Trash2 } from '@lucide/vue'
import { computed, ref, useId, watch } from 'vue'

import type { Case } from '@/api'
import { reviewerName } from '@/composables/reviewer'
import { useCasesStore } from '@/stores/cases'
import { timeAgo } from '@/utils/format'
import ScoreRing from './ScoreRing.vue'
import BaseButton from './ui/BaseButton.vue'

const props = defineProps<{ item: Case }>()
const store = useCasesStore()

// A gap this big between the reviewer and the AI is worth pointing out
const DIFFERS_BY = 20

const reasonErrorId = useId()
const editing = ref(false)
const score = ref(50)
const reason = ref('')
const reasonMissing = ref(false)
const saving = ref(false)
const error = ref<string | null>(null)
const noteText = ref('')
const notesLoading = ref(false)

const review = computed(() => props.item.review ?? null)
const notes = computed(() => [...(store.notes[props.item.id] ?? [])].reverse())
const gap = computed(() =>
  review.value && props.item.score !== null ? review.value.score - props.item.score : null,
)

function startEdit() {
  score.value = review.value?.score ?? props.item.score ?? 50
  reason.value = review.value?.reason ?? ''
  reasonMissing.value = false
  editing.value = true
}

watch(
  () => props.item.id,
  async (id) => {
    editing.value = !review.value
    if (editing.value) startEdit()
    noteText.value = ''
    error.value = null
    notesLoading.value = true
    try {
      await store.loadNotes(id)
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      notesLoading.value = false
    }
  },
  { immediate: true },
)

async function run(action: () => Promise<void>) {
  saving.value = true
  error.value = null
  try {
    await action()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    saving.value = false
  }
}

function saveReview() {
  reasonMissing.value = !reason.value.trim()
  if (reasonMissing.value || !reviewerName.value) return
  run(async () => {
    await store.setReview(props.item.id, score.value, reason.value.trim(), reviewerName.value)
    editing.value = false
  })
}

function removeReview() {
  run(async () => {
    await store.clearReview(props.item.id)
    startEdit()
  })
}

function addNote() {
  const text = noteText.value.trim()
  if (!text || !reviewerName.value) return
  run(async () => {
    await store.addNote(props.item.id, text, reviewerName.value)
    noteText.value = ''
  })
}
</script>

<template>
  <div class="assessment">
    <!-- Reviewer score -->
    <div v-if="review && !editing" class="review">
      <ScoreRing :score="review.score" :size="56" />
      <div class="review-text">
        <p class="review-head">
          <strong>Reviewer score</strong>
          <span class="muted">{{ review.author }} · {{ timeAgo(review.reviewed_at) }}</span>
        </p>
        <p class="reason">“{{ review.reason }}”</p>
        <p v-if="gap !== null" class="compare muted">
          AI score {{ item.score }}
          <span v-if="Math.abs(gap) >= DIFFERS_BY" class="tag tag-mid">
            {{ gap > 0 ? '+' : '' }}{{ gap }} vs AI
          </span>
        </p>
      </div>
      <div class="review-actions">
        <BaseButton size="sm" variant="ghost" :icon="Pencil" @click="startEdit">Edit</BaseButton>
        <BaseButton size="sm" variant="ghost" :disabled="saving" @click="removeReview">
          Remove
        </BaseButton>
      </div>
    </div>

    <form v-else class="score-form" @submit.prevent="saveReview">
      <div class="score-row">
        <ScoreRing :score="score" :size="56" />
        <label class="slider">
          <span class="field-label">
            Your score
            <span v-if="item.score !== null" class="muted">· AI says {{ item.score }}</span>
          </span>
          <input v-model.number="score" type="range" min="0" max="100" step="1" />
        </label>
        <input
          v-model.number="score"
          class="input num"
          type="number"
          min="0"
          max="100"
          aria-label="Your score"
        />
      </div>
      <label class="field">
        <span class="field-label">Why? <span class="muted">(required)</span></span>
        <textarea
          v-model="reason"
          class="input"
          rows="2"
          placeholder="e.g. I know the founders from a previous role; strong team."
          aria-required="true"
          :aria-invalid="reasonMissing"
          :aria-describedby="reasonMissing ? reasonErrorId : undefined"
        />
        <small v-if="reasonMissing" :id="reasonErrorId" class="text-error" role="alert">
          Add a reason for your score.
        </small>
      </label>
      <div class="form-actions">
        <BaseButton v-if="review" size="sm" @click="editing = false">Cancel</BaseButton>
        <BaseButton
          type="submit"
          size="sm"
          variant="primary"
          :loading="saving"
          :disabled="!reviewerName"
        >
          Save score
        </BaseButton>
      </div>
    </form>

    <!-- Notes -->
    <div class="notes">
      <h4>
        Notes <span class="muted">({{ notes.length }})</span>
        <LoaderCircle v-if="notesLoading" class="spin" :size="14" />
      </h4>
      <form class="note-form" @submit.prevent="addNote">
        <textarea
          v-model="noteText"
          class="input"
          rows="2"
          placeholder="Add a note for the team (internal, never in the pitch)"
          aria-label="New note"
          @keydown.ctrl.enter.prevent="addNote"
          @keydown.meta.enter.prevent="addNote"
        />
        <button
          type="submit"
          class="send"
          aria-label="Add note"
          :disabled="saving || !noteText.trim() || !reviewerName"
        >
          <Send :size="16" />
        </button>
      </form>
      <p v-if="error" class="text-error small">{{ error }}</p>
      <ol v-if="notes.length">
        <li v-for="n in notes" :key="n.id">
          <p class="note-head">
            <strong>{{ n.author }}</strong>
            <span class="muted">{{ timeAgo(n.created_at) }}</span>
            <button
              v-if="n.author === reviewerName"
              class="delete"
              aria-label="Delete note"
              :disabled="saving"
              @click="run(() => store.deleteNote(item.id, n.id))"
            >
              <Trash2 :size="14" />
            </button>
          </p>
          <p class="note-text">{{ n.text }}</p>
        </li>
      </ol>
    </div>
  </div>
</template>

<style scoped>
.assessment {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}
.small {
  font-size: 0.9375rem;
}
.field-label {
  font-size: 1rem;
  font-weight: 600;
}

.review {
  display: flex;
  gap: 0.9rem;
  padding: 0.9rem 1rem;
  border-radius: var(--radius-lg);
  background: var(--surface-alt);
}
.review-text {
  flex: 1;
  min-width: 0;
}
.review-head {
  display: flex;
  flex-wrap: wrap;
  gap: 0.2rem 0.5rem;
  align-items: baseline;
  font-size: 1rem;
}
.review-head .muted {
  font-size: 0.9375rem;
}
.reason {
  margin-top: 0.2rem;
  font-size: 1rem;
  font-style: italic;
}
.compare {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.35rem;
  font-size: 0.9375rem;
}
.review-actions {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.score-form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 0.9rem 1rem;
  border-radius: var(--radius-lg);
  background: var(--surface-alt);
}
.score-row {
  display: flex;
  align-items: center;
  gap: 0.9rem;
}
.slider {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.slider input {
  width: 100%;
  accent-color: var(--text);
}
.num {
  width: 4.5rem;
  height: 36px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
textarea.input {
  height: auto;
  padding: 0.55rem 0.75rem;
  resize: vertical;
  line-height: 1.45;
}
textarea.input[aria-invalid='true'] {
  border-color: var(--bad);
}
.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
}

.notes h4 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-bottom: 0.5rem;
  font-size: 1.0625rem;
}
.note-form {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}
.send {
  flex: none;
  display: grid;
  place-items: center;
  width: 38px;
  height: 38px;
  border: 0;
  border-radius: 999px;
  background: var(--text);
  color: #fff;
  cursor: pointer;
}
.send:disabled {
  background: var(--border-strong);
  cursor: not-allowed;
}
.send:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
ol {
  list-style: none;
  padding: 0;
  margin-top: 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
li {
  padding-left: 0.8rem;
  border-left: 2px solid var(--border);
}
.note-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9375rem;
}
.note-text {
  font-size: 1rem;
  white-space: pre-wrap;
}
.delete {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  margin-left: auto;
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--text-faint);
  cursor: pointer;
}
.delete:hover {
  background: var(--bern-red-tint);
  color: var(--bern-red);
}
</style>
