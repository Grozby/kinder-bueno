import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import {
  backend,
  type Case,
  type CaseNote,
  type CaseStatus,
  type ChatResponse,
  type Pitch,
  type CaseDocuments,
  type Rating,
  type Result,
} from '@/api'

export const DEFAULT_REFERENCES = 10
export const MAX_REFERENCES = 25
const POLL_MS = 1500
const DOCUMENTS_POLL_MS = 2000 // the report and slides take about a minute

export interface ChatTurn {
  message: string
  response: ChatResponse | null // null while waiting
  error: string | null
}

// One chat session per case, so the agent keeps the context of that company's refinements
const sessionId = (caseId: string) => `case-${caseId}`

export const useCasesStore = defineStore('cases', () => {
  const cases = ref<Case[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const uploading = ref(0)
  // The discarded (rejected) cases panel; opened from the sidebar, shown on the board
  const showDiscarded = ref(false)

  // Per case: references (backend top 25, plus results added from the chat), the entity ids
  // chosen for the pitch, the last pitch, the chat turns, the feedback given per entity,
  // and the claims flagged as wrong facts
  const references = ref<Record<string, Result[]>>({})
  const selected = ref<Record<string, number[]>>({})
  const pitches = ref<Record<string, Pitch>>({})
  const documents = ref<Record<string, CaseDocuments>>({})
  const chats = ref<Record<string, ChatTurn[]>>({})
  const ratings = ref<Record<string, Record<number, Rating>>>({})
  const flagged = ref<Record<string, number[]>>({})
  const notes = ref<Record<string, CaseNote[]>>({})

  const byStatus = computed(() => {
    const groups: Record<CaseStatus, Case[]> = {
      new: [],
      in_review: [],
      accepted: [],
      rejected: [],
    }
    for (const c of cases.value) groups[c.status].push(c)
    for (const list of Object.values(groups)) {
      list.sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
    }
    return groups
  })

  function upsert(c: Case) {
    const i = cases.value.findIndex((x) => x.id === c.id)
    if (i === -1) cases.value.push(c)
    else cases.value[i] = c
  }

  async function poll(id: string) {
    while (true) {
      await new Promise((resolve) => setTimeout(resolve, POLL_MS))
      try {
        const c = await backend.getCase(id)
        upsert(c)
        if (c.analysis_status !== 'pending') return
      } catch {
        return
      }
    }
  }

  async function load() {
    loading.value = true
    error.value = null
    try {
      cases.value = await backend.listCases()
      cases.value.filter((c) => c.analysis_status === 'pending').forEach((c) => poll(c.id))
    } catch (e) {
      error.value = (e as Error).message
    } finally {
      loading.value = false
    }
  }

  async function upload(file: File) {
    uploading.value++
    try {
      const c = await backend.uploadCase(file)
      upsert(c)
      if (c.analysis_status === 'pending') poll(c.id)
      return c
    } finally {
      uploading.value--
    }
  }

  // Optimistic: the card moves right away and moves back if the backend refuses
  async function move(id: string, status: CaseStatus) {
    const c = cases.value.find((x) => x.id === id)
    if (!c || c.status === status) return
    const previous = c.status
    c.status = status
    try {
      upsert(await backend.setCaseStatus(id, status))
    } catch (e) {
      c.status = previous
      throw e
    }
  }

  // The drawer's state is kept by the backend (#81): references (top 25 plus the ones added from
  // the chat), the selection, the chat turns and the feedback all come back after a reload
  async function loadReferences(id: string) {
    if (references.value[id]) return
    const [refs, selection, turns, feedback] = await Promise.all([
      backend.listReferences(id, MAX_REFERENCES),
      backend.getSelection(id),
      backend.getCaseChat(id),
      backend.getCaseFeedback(id),
    ])
    references.value[id] = refs
    selected.value[id] = selection.entity_ids
    chats.value[id] ??= turns.map((t) => ({
      message: t.message,
      response: t.response,
      error: null,
    }))
    ratings.value[id] = { ...feedback.ratings, ...ratings.value[id] }
    flagged.value[id] = [...new Set([...feedback.flagged, ...(flagged.value[id] ?? [])])]
  }

  // Optimistic: the checkbox changes right away and changes back if the backend refuses
  async function saveSelection(caseId: string, entityIds: number[]) {
    const previous = selected.value[caseId] ?? []
    selected.value[caseId] = entityIds
    try {
      selected.value[caseId] = (await backend.setSelection(caseId, entityIds)).entity_ids
    } catch (e) {
      selected.value[caseId] = previous
      throw e
    }
  }

  function toggleReference(caseId: string, entityId: number) {
    const list = selected.value[caseId] ?? []
    const next = list.includes(entityId) ? list.filter((e) => e !== entityId) : [...list, entityId]
    return saveSelection(caseId, next)
  }

  // A chat result the user liked: becomes a reference of the case, selected for the pitch
  async function addReference(caseId: string, result: Result) {
    const added = await backend.addReference(caseId, result.entity_id)
    const list = (references.value[caseId] ??= [])
    if (!list.some((r) => r.entity_id === added.entity_id)) list.push(added)
    const chosen = selected.value[caseId] ?? []
    if (!chosen.includes(added.entity_id)) await saveSelection(caseId, [...chosen, added.entity_id])
  }

  async function sendChat(caseId: string, message: string) {
    const turns = (chats.value[caseId] ??= [])
    turns.push({ message, response: null, error: null })
    const turn = turns[turns.length - 1]!
    try {
      turn.response = await backend.chat({ session_id: sessionId(caseId), message })
    } catch (e) {
      turn.error = (e as Error).message
    }
  }

  async function rate(caseId: string, query: string, entityId: number, rating: Rating) {
    await backend.feedback({ session_id: sessionId(caseId), query, entity_id: entityId, rating })
    ;(ratings.value[caseId] ??= {})[entityId] = rating
  }

  async function flagFact(caseId: string, query: string, entityId: number, claimId: number) {
    await backend.feedback({
      session_id: sessionId(caseId),
      query,
      entity_id: entityId,
      claim_id: claimId,
      rating: 'wrong_fact',
    })
    ;(flagged.value[caseId] ??= []).push(claimId)
  }

  // After a reload: the last pitch stored on the case
  async function loadPitch(id: string) {
    if (pitches.value[id]) return
    const pitch = await backend.getPitch(id)
    if (pitch) pitches.value[id] = pitch
  }

  async function generatePitch(id: string) {
    const pitch = await backend.generatePitch(id, selected.value[id] ?? [])
    pitches.value[id] = pitch
    return pitch
  }

  // Partner report and slides (#96): made in the background, so poll until the job is no longer pending
  async function pollDocuments(id: string) {
    while (documents.value[id]?.status === 'pending') {
      await new Promise((resolve) => setTimeout(resolve, DOCUMENTS_POLL_MS))
      documents.value[id] = await backend.getDocuments(id)
    }
  }

  async function loadDocuments(id: string) {
    documents.value[id] = await backend.getDocuments(id)
    await pollDocuments(id) // a job started before a reload
  }

  async function generateDocuments(id: string) {
    documents.value[id] = await backend.generateDocuments(id)
    await pollDocuments(id)
  }

  // The reviewer's own score and notes; the author is the name given in this browser
  async function setReview(id: string, score: number, reason: string, author: string) {
    upsert(await backend.setReview(id, { score, reason, author }))
  }

  async function clearReview(id: string) {
    upsert(await backend.clearReview(id))
  }

  async function loadNotes(id: string) {
    notes.value[id] = await backend.listNotes(id)
  }

  function countNotes(id: string) {
    const c = cases.value.find((x) => x.id === id)
    if (c) c.notes_count = notes.value[id]?.length ?? 0
  }

  async function addNote(id: string, text: string, author: string) {
    const note = await backend.addNote(id, { author, text })
    ;(notes.value[id] ??= []).push(note)
    countNotes(id)
  }

  async function deleteNote(id: string, noteId: string) {
    await backend.deleteNote(id, noteId)
    notes.value[id] = (notes.value[id] ?? []).filter((n) => n.id !== noteId)
    countNotes(id)
  }

  return {
    cases,
    loading,
    error,
    uploading,
    showDiscarded,
    references,
    selected,
    pitches,
    documents,
    chats,
    ratings,
    flagged,
    notes,
    byStatus,
    load,
    upload,
    move,
    loadReferences,
    toggleReference,
    addReference,
    sendChat,
    rate,
    flagFact,
    loadPitch,
    generatePitch,
    loadDocuments,
    generateDocuments,
    setReview,
    clearReview,
    loadNotes,
    addNote,
    deleteNote,
  }
})
