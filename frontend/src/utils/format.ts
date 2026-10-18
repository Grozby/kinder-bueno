export type ScoreBand = 'good' | 'mid' | 'bad'

export function scoreBand(score: number): ScoreBand {
  if (score >= 70) return 'good'
  if (score >= 45) return 'mid'
  return 'bad'
}

const rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
const UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['day', 86_400],
  ['hour', 3_600],
  ['minute', 60],
]

export function timeAgo(iso: string): string {
  const seconds = (new Date(iso).getTime() - Date.now()) / 1000
  for (const [unit, size] of UNITS) {
    if (Math.abs(seconds) >= size) return rtf.format(Math.round(seconds / size), unit)
  }
  return 'just now'
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}
