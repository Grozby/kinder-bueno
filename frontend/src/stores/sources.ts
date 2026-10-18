import { defineStore } from 'pinia'
import { ref } from 'vue'

import { backend, type NewSource, type Source } from '@/api'

const POLL_MS = 1000

export const useSourcesStore = defineStore('sources', () => {
  const sources = ref<Source[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

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
        if (s.status !== 'crawling') return
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

  return { sources, loading, error, load, add }
})
