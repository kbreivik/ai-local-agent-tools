/**
 * versionCheck.js — Docker Hub semver tag lookup utilities (pure JS, no JSX).
 * VersionBadge React component is in utils/VersionBadge.jsx.
 * Caches results in a module-level Map with 1hr TTL.
 */

const _cache = new Map()   // key → { tag: string | null, fetchedAt: number }
const TTL_MS = 60 * 60 * 1000   // 1 hour

/**
 * Return the latest stable semver tag for a Docker image.
 * image may include tag/digest — they are stripped before lookup.
 * Returns null on error (caller should show nothing).
 */
export async function getLatestTag(image) {
  if (!image) return null

  // Strip tag and digest → get bare repo name
  const bare = image.split('@')[0].split(':')[0].trim()
  if (!bare) return null

  const cached = _cache.get(bare)
  if (cached && Date.now() - cached.fetchedAt < TTL_MS) {
    return cached.tag
  }

  const repo = bare.includes('/') ? bare : `library/${bare}`
  const url  = `https://hub.docker.com/v2/repositories/${repo}/tags?page_size=25&ordering=last_updated`

  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(8000) })
    if (!r.ok) { _cache.set(bare, { tag: null, fetchedAt: Date.now() }); return null }
    const data = await r.json()
    const tags = (data.results ?? []).map(t => t.name)

    const EXCLUDE = /rc|beta|alpha|snapshot|latest/i
    const SEMVER3 = /^\d+\.\d+\.\d+$/

    const stable = tags.filter(t => SEMVER3.test(t) && !EXCLUDE.test(t))
    if (!stable.length) { _cache.set(bare, { tag: null, fetchedAt: Date.now() }); return null }

    stable.sort((a, b) => _cmpTuple(_toTuple(a), _toTuple(b)))
    const latest = stable[0]
    _cache.set(bare, { tag: latest, fetchedAt: Date.now() })
    return latest
  } catch {
    // Network error — fail silently
    _cache.set(bare, { tag: null, fetchedAt: Date.now() })
    return null
  }
}

function _toTuple(v) {
  return v.split('.').map(n => parseInt(n, 10) || 0)
}

function _cmpTuple(a, b) {
  for (let i = 0; i < 3; i++) {
    const d = (b[i] ?? 0) - (a[i] ?? 0)
    if (d !== 0) return d
  }
  return 0
}

/**
 * Compare two semver strings.
 * Returns: "current" | "patch" | "minor" | "major" | "ahead" | "unknown"
 */
export function compareSemver(current, latest) {
  if (!current || !latest) return 'unknown'

  // Normalize: strip non-numeric suffix before first non-dot/digit
  const parseV = s => {
    const parts = s.split('.').slice(0, 3).map(n => parseInt(n, 10))
    return parts.every(n => !isNaN(n)) ? parts : null
  }

  const cur = parseV(current)
  const lat = parseV(latest)
  if (!cur || !lat) return 'unknown'

  if (cur[0] === lat[0] && cur[1] === lat[1] && cur[2] === lat[2]) return 'current'
  if (lat[0] > cur[0]) return 'major'
  if (lat[0] === cur[0] && lat[1] > cur[1]) return 'minor'
  if (lat[0] === cur[0] && lat[1] === cur[1] && lat[2] > cur[2]) return 'patch'
  return 'ahead'
}
