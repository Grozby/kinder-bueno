// URL patterns for the crawl rules. They are regular expressions, matched with search semantics
// like Python's re.search in the crawler; keep them to the syntax both languages share.

const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// Exactly this page
export function exactPattern(url: string): string {
  return `^${escape(url)}$`
}

// The page's folder and everything below it: a good first guess for "block pages like this"
export function folderPattern(url: string): string {
  const u = new URL(url)
  const folder = u.pathname.endsWith('/')
    ? u.pathname.replace(/[^/]+\/$/, '')
    : u.pathname.replace(/[^/]*$/, '')
  return `^${escape(u.origin + folder)}`
}

export function isValidPattern(pattern: string): boolean {
  try {
    new RegExp(pattern)
    return pattern.trim() !== ''
  } catch {
    return false
  }
}

export function matches(pattern: string, url: string): boolean {
  try {
    return new RegExp(pattern).test(url)
  } catch {
    return false
  }
}
