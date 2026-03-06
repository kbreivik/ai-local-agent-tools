/**
 * VersionBadge — shows an upgrade indicator next to an image version.
 * Uses getLatestTag() from versionCheck.js (cached, async).
 */
import { useEffect, useState } from 'react'
import { getLatestTag, compareSemver } from './versionCheck'

/**
 * Props:
 *   image      — full image string (e.g. "nginx:1.25-alpine" or bare "nginx")
 *   currentTag — the tag currently in use (e.g. "1.25-alpine")
 *
 * While loading: nothing. On error: nothing. Tooltip on hover.
 */
export default function VersionBadge({ image, currentTag }) {
  const [result, setResult] = useState(null)   // { comparison, latest }

  useEffect(() => {
    if (!image || !currentTag) return
    let cancelled = false
    getLatestTag(image).then(latest => {
      if (cancelled || !latest) return
      setResult({ comparison: compareSemver(currentTag, latest), latest })
    })
    return () => { cancelled = true }
  }, [image, currentTag])

  if (!result) return null

  const { comparison, latest } = result
  const title = `Latest stable: ${latest} — Current: ${currentTag}`

  switch (comparison) {
    case 'current':
      return <span className="text-green-400 text-xs" title={title}>✓ latest</span>
    case 'patch':
    case 'minor':
      return <span className="text-yellow-400 text-xs" title={title}>⬆ {latest}</span>
    case 'major':
      return <span className="text-red-400 text-xs" title={title}>⬆ {latest} (major)</span>
    default:
      return null
  }
}
