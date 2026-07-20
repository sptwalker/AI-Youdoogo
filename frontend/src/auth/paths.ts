/** Keep post-login navigation on this SPA origin. Backend validation remains authoritative. */
export function normalizeAppPath(value: string | null | undefined): string {
  if (!value || value.length > 2048) return '/'

  let decoded: string
  try {
    decoded = decodeURIComponent(value)
  } catch {
    return '/'
  }
  if (
    !decoded.startsWith('/')
    || decoded.startsWith('//')
    || decoded.includes('\\')
    || [...decoded].some((character) => {
      const codePoint = character.codePointAt(0) ?? 0
      return codePoint < 32 || codePoint === 127
    })
  ) return '/'

  try {
    const parsed = new URL(value, window.location.origin)
    if (parsed.origin !== window.location.origin || parsed.hash) return '/'
    return `${parsed.pathname}${parsed.search}`
  } catch {
    return '/'
  }
}
