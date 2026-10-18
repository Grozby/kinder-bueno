import { defineStore } from 'pinia'
import { ref } from 'vue'

import {
  backend,
  type CrawlRules,
  type NewSource,
  type ResourcePage,
  type RuleKind,
  type Source,
} from '@/api'

const POLL_MS = 1000

export const useSourcesStore = defineStore('sources', () => {
  const sources = ref<Source[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  // Resources: every crawled page with its score, and each source's crawl rules
  const pages = ref<ResourcePage[]>([])
  const pagesLoading = ref(false)
  const pagesError = ref<string | null>(null)
  const rules = ref<Record<string, CrawlRules>>({})

  function upsert(s: Source) {
    const i = sources.value.findIndex((x) => x.id === s.id)
    if (i === -1) sources.value.unshift(s)
    else sources.value[i] = s
  }

  async function poll(id: string) {
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
      try {
        const s = await backend.getSource(id)
        upsert(s)
        if (s.status !== 'crawling') {
          if (pages.value.length) loadPages()
          return
        }
      } catch {
        return
      }
    }
  }

  async function load() {
    loading.value = true
    error.value = null
    try {
      sources.value = await backend.listSources()
      sources.value.filter((s) => s.status === 'crawling').forEach((s) => poll(s.id))
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function add(input: NewSource) {
    const s = await backend.addSource(input)
    upsert(s)
    if (s.status === 'crawling') poll(s.id)
    return s
  }

  async function recrawl(id: string) {
    const s = await backend.recrawlSource(id)
    upsert(s)
    poll(id)
  }

  async function loadPages() {
    pagesLoading.value = true
    pagesError.value = null
    try {
      pages.value = await backend.listPages()
    } catch (e) {
      pagesError.value = (e as Error).message
    } finally {
      pagesLoading.value = false
    }
  }

  async function loadRules(id: string) {
    rules.value[id] = await backend.getRules(id)
    return rules.value[id]
  }

  // Saving rules changes which pages are blocked at once, so the page list is reloaded
  async function saveRules(id: string, next: Record<RuleKind, string[]>) {
    const { allow_hosts, include_patterns, exclude_patterns, priority_patterns } = next
    rules.value[id] = await backend.setRules(id, {
      allow_hosts,
      include_patterns,
      exclude_patterns,
      priority_patterns,
    })
    await loadPages()
  }

  async function addRule(id: string, kind: RuleKind, pattern: string) {
    const current = rules.value[id] ?? (await loadRules(id))
    if (current[kind].includes(pattern)) return
    await saveRules(id, { ...current, [kind]: [...current[kind], pattern] })
  }

  async function removeRule(id: string, kind: RuleKind, pattern: string) {
    const current = rules.value[id] ?? (await loadRules(id))
    await saveRules(id, { ...current, [kind]: current[kind].filter((p) => p !== pattern) })
  }

  return {
    sources,
    loading,
    error,
    pages,
    pagesLoading,
    pagesError,
    rules,
    load,
    add,
    recrawl,
    loadPages,
    loadRules,
    saveRules,
    addRule,
    removeRule,
  }
})
