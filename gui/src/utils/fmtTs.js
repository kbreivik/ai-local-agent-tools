/**
 * Shared time formatters for Logs sub-pages + anywhere else a
 * timestamp renders. v2.38.5 replaces three inconsistent local
 * implementations (time-only toLocaleTimeString, mixed toLocaleString,
 * AgentActionsTab's full datetime) with one gold-standard output:
 * 24-hour "YYYY-MM-DD HH:MM:SS".
 *
 * No locale-dependent month names. No AM/PM. Forensic-grade second
 * resolution for log correlation.
 */

/**
 * "2026-04-21 14:32:08" — the primary format for every timestamp cell
 * in the Logs tab. Returns 'N/A' on null/undefined/invalid input so
 * callers don't need to defend against bad data.
 */
export function fmtDateTime(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  // Use toLocaleString with a fixed, browser-independent format
  const yyyy = d.getFullYear()
  const mm   = String(d.getMonth() + 1).padStart(2, '0')
  const dd   = String(d.getDate()).padStart(2, '0')
  const hh   = String(d.getHours()).padStart(2, '0')
  const mi   = String(d.getMinutes()).padStart(2, '0')
  const ss   = String(d.getSeconds()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`
}

/**
 * "2026-04-21" — date only. Useful for column headers or grouping.
 */
export function fmtDate(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  const yyyy = d.getFullYear()
  const mm   = String(d.getMonth() + 1).padStart(2, '0')
  const dd   = String(d.getDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/**
 * "14:32:08" — time only, 24h, seconds included. Used in compact
 * rows where date is redundant (e.g. within-session raw output
 * feeds where every line is from the same day).
 */
export function fmtTime(iso) {
  if (!iso) return 'N/A'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return 'N/A'
  const hh   = String(d.getHours()).padStart(2, '0')
  const mi   = String(d.getMinutes()).padStart(2, '0')
  const ss   = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${mi}:${ss}`
}
