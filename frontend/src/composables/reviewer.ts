// Who is writing notes and scores. There are no user accounts (PLAN.md non-goals), so the name is
// asked once and remembered in this browser only.
import { ref } from 'vue'

const KEY = 'bern-fit:reviewer'

function read(): string {
  try {
    return localStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

export const reviewerName = ref(read())
// The name prompt is open: on first visit (no name yet), or when the reviewer asks to change it
export const askingName = ref(!reviewerName.value)

export function askReviewerName() {
  askingName.value = true
}

export function setReviewerName(name: string) {
  askingName.value = false
  reviewerName.value = name.trim()
  try {
    localStorage.setItem(KEY, reviewerName.value)
  } catch {
    // Private mode or blocked storage: the name lasts until the page is reloaded
  }
}
