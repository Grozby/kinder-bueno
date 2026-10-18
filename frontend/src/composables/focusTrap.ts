// Keeps Tab and Shift+Tab inside an open dialog, so keyboard users cannot land on the page
// behind it (WCAG 2.4.3). Call it from the dialog's keydown handler.

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export function trapFocus(e: KeyboardEvent, container: HTMLElement | null) {
  if (e.key !== 'Tab' || !container) return
  const items = [...container.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (el) => el.getClientRects().length > 0,
  )
  const first = items[0]
  const last = items[items.length - 1]
  if (!first || !last) {
    e.preventDefault()
    container.focus()
  } else if (
    e.shiftKey &&
    (document.activeElement === first || document.activeElement === container)
  ) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}
