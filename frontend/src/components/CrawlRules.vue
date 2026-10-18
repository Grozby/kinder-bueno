<script setup lang="ts">
// The crawl rules of one source (config/sources.yaml): allowed hosts and the include, exclude
// and priority URL patterns. Each pattern shows how many crawled pages it matches.
import { LoaderCircle, Plus, RefreshCw, X } from '@lucide/vue'
import { computed, onMounted, reactive, ref } from 'vue'

import type { RuleKind, Source } from '@/api'
import { useSourcesStore } from '@/stores/sources'
import { isValidPattern, matches } from '@/utils/patterns'
import BaseButton from './ui/BaseButton.vue'

const props = defineProps<{ source: Source }>()
const store = useSourcesStore()

const GROUPS: Array<{ kind: RuleKind; title: string; hint: string; placeholder: string }> = [
  {
    kind: 'exclude_patterns',
    title: 'Blocked',
    hint: 'Pages matching these are hidden from results at once and skipped by the crawler.',
    placeholder: '/news/',
  },
  {
    kind: 'priority_patterns',
    title: 'Priority',
    hint: 'The crawler spends its page budget on these first.',
    placeholder: '/research/[a-z_]+/index_eng\\.html$',
  },
  {
    kind: 'include_patterns',
    title: 'Included',
    hint: 'Only pages matching one of these are crawled.',
    placeholder: 'index_eng\\.html$',
  },
  {
    kind: 'allow_hosts',
    title: 'Allowed hosts',
    hint: 'Websites the crawler may follow links to.',
    placeholder: 'www.example.unibe.ch',
  },
]

const loading = ref(true)
const busy = ref(false)
const error = ref<string | null>(null)
const draft = reactive<Record<RuleKind, string>>({
  allow_hosts: '',
  include_patterns: '',
  exclude_patterns: '',
  priority_patterns: '',
})

const rules = computed(() => store.rules[props.source.id])
const sourcePages = computed(() => store.pages.filter((p) => p.source_id === props.source.id))
// Compared as dates: the two timestamps are not always formatted alike (fractional seconds)
const stale = computed(
  () =>
    !!rules.value?.changed_at &&
    (!props.source.last_crawled_at ||
      Date.parse(rules.value.changed_at) > Date.parse(props.source.last_crawled_at)),
)

function matchCount(kind: RuleKind, pattern: string) {
  if (kind === 'allow_hosts') return null
  return sourcePages.value.filter((p) => matches(pattern, p.url)).length
}

function draftValid(kind: RuleKind) {
  const value = draft[kind].trim()
  return kind === 'allow_hosts' ? /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(value) : isValidPattern(value)
}

async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = null
  try {
    await action()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function add(kind: RuleKind) {
  if (!draftValid(kind)) return
  const value = draft[kind].trim()
  run(async () => {
    await store.addRule(props.source.id, kind, value)
    draft[kind] = ''
  })
}

onMounted(async () => {
  try {
    await Promise.all([
      store.loadRules(props.source.id),
      store.pages.length ? null : store.loadPages(),
    ])
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <section class="rules">
    <div class="rules-head">
      <h3 class="section-label">Crawl rules</h3>
      <LoaderCircle v-if="busy" class="spin" :size="16" />
    </div>

    <p v-if="stale" class="stale">
      <span>
        Rules changed since the last crawl. Blocked pages are already hidden; re-crawl to spend the
        page budget on the new rules.
      </span>
      <BaseButton
        size="sm"
        :icon="RefreshCw"
        :disabled="source.status === 'crawling'"
        @click="run(() => store.recrawl(source.id))"
      >
        {{ source.status === 'crawling' ? 'Crawling…' : 'Re-crawl' }}
      </BaseButton>
    </p>
    <p v-if="error" class="text-error">{{ error }}</p>
    <p v-if="loading" class="muted"><LoaderCircle class="spin" :size="16" /></p>

    <div v-else-if="rules" class="groups">
      <div v-for="g in GROUPS" :key="g.kind" class="group">
        <h4>{{ g.title }}</h4>
        <p class="hint">{{ g.hint }}</p>
        <ul>
          <li v-for="pattern in rules[g.kind]" :key="pattern">
            <code>{{ pattern }}</code>
            <span v-if="matchCount(g.kind, pattern) !== null" class="hits">
              {{ matchCount(g.kind, pattern) }} pages
            </span>
            <button
              class="remove"
              :aria-label="`Remove ${pattern}`"
              :disabled="busy"
              @click="run(() => store.removeRule(source.id, g.kind, pattern))"
            >
              <X :size="14" />
            </button>
          </li>
          <li v-if="!rules[g.kind].length" class="none">None</li>
        </ul>
        <form class="add" @submit.prevent="add(g.kind)">
          <input
            v-model="draft[g.kind]"
            class="input"
            :placeholder="g.placeholder"
            :aria-label="`Add to ${g.title}`"
            :aria-invalid="!!draft[g.kind] && !draftValid(g.kind)"
          />
          <button
            type="submit"
            class="add-btn"
            :disabled="busy || !draftValid(g.kind)"
            aria-label="Add"
          >
            <Plus :size="16" />
          </button>
        </form>
      </div>
    </div>
  </section>
</template>

<style scoped>
.rules-head {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}
.rules-head .section-label {
  margin: 0;
}
.stale {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  border-radius: var(--radius);
  background: var(--mid-tint);
  color: var(--text);
  font-size: 1rem;
}
.stale span {
  flex: 1;
}
.groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.group {
  display: flex;
  flex-direction: column;
  padding: 0.9rem 1rem;
  border-radius: var(--radius-lg);
  background: var(--surface-alt);
}
h4 {
  font-size: 1.0625rem;
}
.hint {
  margin-bottom: 0.6rem;
  font-size: 0.9375rem;
  color: var(--text-muted);
}
ul {
  list-style: none;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  margin-bottom: 0.6rem;
}
li {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.25rem 0.3rem 0.25rem 0.6rem;
  border-radius: var(--radius);
  background: var(--surface);
  border: 1px solid var(--border-soft);
}
li.none {
  color: var(--text-faint);
  font-size: 0.9375rem;
  padding: 0.35rem 0.6rem;
}
code {
  flex: 1;
  min-width: 0;
  font-family: var(--mono);
  font-size: 0.875rem;
  word-break: break-all;
}
.hits {
  flex: none;
  font-size: 0.875rem;
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}
.remove,
.add-btn {
  flex: none;
  display: grid;
  place-items: center;
  border: 0;
  border-radius: 999px;
  cursor: pointer;
}
.remove {
  width: 24px;
  height: 24px;
  background: transparent;
  color: var(--text-muted);
}
.remove:hover {
  background: var(--bern-red-tint);
  color: var(--bern-red);
}
.add {
  display: flex;
  gap: 0.4rem;
  margin-top: auto;
}
.add .input {
  height: 34px;
  font-family: var(--mono);
  font-size: 0.9062rem;
}
.add .input[aria-invalid='true'] {
  border-color: var(--bad);
}
.add-btn {
  width: 34px;
  height: 34px;
  background: var(--text);
  color: #fff;
}
.add-btn:disabled {
  background: var(--border-strong);
  cursor: not-allowed;
}
.remove:focus-visible,
.add-btn:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
</style>
