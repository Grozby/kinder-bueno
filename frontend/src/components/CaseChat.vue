<script setup lang="ts">
// Refine a case's references in a conversation (POST /api/chat, docs/PLAN.md 8.10).
// Results can be added to the case; added ones are selected for the pitch.
import { Check, LoaderCircle, Plus, Send } from '@lucide/vue'
import { computed, nextTick, ref, useTemplateRef } from 'vue'

import { SHOW_UNFINISHED } from '@/api'
import { useCasesStore } from '@/stores/cases'
import { hostOf } from '@/utils/format'
import BaseButton from './ui/BaseButton.vue'

const props = defineProps<{ caseId: string }>()

const store = useCasesStore()
const draft = ref('')
const log = useTemplateRef<HTMLElement>('log')

const turns = computed(() => store.chats[props.caseId] ?? [])
const busy = computed(() => turns.value.some((t) => !t.response && !t.error))
const referenceIds = computed(
  () => new Set((store.references[props.caseId] ?? []).map((r) => r.entity_id)),
)

const EXAMPLES = ['Only people at DCB', 'More like #1', 'Who works with #2?']

async function send(message = draft.value.trim()) {
  if (!message || busy.value) return
  draft.value = ''
  const sending = store.sendChat(props.caseId, message)
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight, behavior: 'smooth' })
  await sending
  await nextTick()
  log.value?.scrollTo({ top: log.value.scrollHeight, behavior: 'smooth' })
}
</script>

<template>
  <div class="chat">
    <div ref="log" class="log">
      <p v-if="!turns.length" class="muted intro">
        Ask for other experts, units or infrastructure for this company. Results you add become
        references and are used in the pitch.
      </p>
      <div v-for="(t, i) in turns" :key="i" class="turn">
        <p class="msg">{{ t.message }}</p>
        <p v-if="t.error" class="reply text-error">The chat failed: {{ t.error }}</p>
        <p v-else-if="!t.response" class="reply muted">
          <LoaderCircle class="spin" :size="14" /> Searching…
        </p>
        <template v-else>
          <p class="reply">{{ t.response.reply }}</p>
          <p v-if="t.response.no_result" class="muted small">
            No reliable source found for this query. Try other words.
          </p>
          <ol v-else class="results">
            <li v-for="r in t.response.results" :key="r.entity_id">
              <div class="result-main">
                <strong>{{ r.name }}</strong>
                <span class="muted small">{{ r.affiliations.join(', ') }}</span>
                <span class="small">{{ r.why }}</span>
                <a
                  v-for="u in r.sources.slice(0, 2)"
                  :key="u"
                  :href="u"
                  target="_blank"
                  rel="noopener"
                >
                  {{ hostOf(u) }}
                </a>
              </div>
              <BaseButton
                size="sm"
                :variant="referenceIds.has(r.entity_id) ? 'ghost' : 'secondary'"
                :icon="referenceIds.has(r.entity_id) ? Check : Plus"
                :disabled="referenceIds.has(r.entity_id)"
                @click="store.addReference(caseId, r)"
              >
                {{ referenceIds.has(r.entity_id) ? 'Added' : 'Add' }}
              </BaseButton>
            </li>
          </ol>
        </template>
      </div>
    </div>

    <div v-if="SHOW_UNFINISHED" class="examples">
      <button v-for="ex in EXAMPLES" :key="ex" type="button" :disabled="busy" @click="send(ex)">
        {{ ex }}
      </button>
    </div>
    <form class="composer" @submit.prevent="send()">
      <input
        v-model="draft"
        class="input"
        type="text"
        placeholder="e.g. glucose sensor experts at the University of Bern"
        aria-label="Message"
      />
      <BaseButton
        type="submit"
        variant="primary"
        :icon="Send"
        :loading="busy"
        :disabled="!draft.trim()"
      >
        Send
      </BaseButton>
    </form>
  </div>
</template>

<style scoped>
.chat {
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
}
.log {
  max-height: 360px;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}
.intro {
  font-size: 1rem;
}
.small {
  font-size: 0.9375rem;
}
.turn {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
.msg {
  align-self: flex-end;
  max-width: 85%;
  padding: 0.5rem 0.8rem;
  background: var(--text);
  color: #fff;
  border-radius: var(--radius);
}
.reply {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
}
.results {
  list-style: none;
  padding: 0;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
}
.results li {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.6rem 0.75rem;
}
.results li + li {
  border-top: 1px solid var(--border-soft);
}
.result-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}
.result-main a {
  font-size: 0.9375rem;
  color: var(--bern-red);
  text-decoration: none;
}
.result-main a:hover {
  text-decoration: underline;
}

.examples {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem;
  padding: 0 1rem 0.75rem;
}
.examples button {
  padding: 0.2rem 0.6rem;
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--surface);
  color: var(--text-muted);
  font: inherit;
  font-size: 0.9375rem;
  cursor: pointer;
}
.examples button:hover:not(:disabled) {
  border-color: var(--text);
  color: var(--text);
}
.composer {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem;
  border-top: 1px solid var(--border-soft);
  background: var(--surface-alt);
}
</style>
