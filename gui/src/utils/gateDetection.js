// Gate-fired detection — UI-side mirror of api/agents/gate_detection.py.
// Keep in sync: a snapshot test on a fixture should produce identical counts
// on both sides. See v2.34.16 CHANGELOG.

export const GATE_DEFS = [
  'halluc_guard',
  'fabrication',
  'distrust',
  'budget_truncate',
  'budget_nudge',
  'sanitizer',
  'forced_synthesis',
  'inrun_contradiction',
]

function emptyGates() {
  const g = {}
  for (const k of GATE_DEFS) g[k] = { count: 0, details: [] }
  return g
}

function asString(v) {
  if (typeof v === 'string') return v
  if (v == null) return ''
  try { return String(v) } catch (e) { return '' }
}

function countFabrication(steps) {
  let count = 0
  for (const s of steps || []) {
    for (const m of s?.messages_delta || []) {
      if (!m || m.role !== 'tool') continue
      const c = asString(m.content)
      if (!c.includes('fabrication_detected')) continue
      try {
        const payload = JSON.parse(c)
        if (payload?.harness_guard?.fabrication_detected) count++
      } catch (e) {
        // Non-JSON tool result — skip
      }
    }
  }
  return count
}

export function detectGates(steps) {
  const gates = emptyGates()
  for (const s of steps || []) {
    const stepIdx = s?.step_index ?? 0
    for (const m of s?.messages_delta || []) {
      const c = asString(m?.content)
      if (!c) continue
      const lc = c.toLowerCase()

      if (c.includes('[harness]') && lc.includes('substantive tool call')) {
        gates.halluc_guard.count++
        gates.halluc_guard.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      if (c.includes('[harness]') && lc.includes('flagged') &&
          (lc.includes('fabrication') || lc.includes('halluc_guard_fired'))) {
        gates.distrust.count++
        gates.distrust.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      if (c.includes('[harness]') && lc.includes('tool budget')) {
        gates.budget_truncate.count++
        gates.budget_truncate.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      if (lc.includes('harness nudge') && lc.includes('propose_subtask')) {
        gates.budget_nudge.count++
        gates.budget_nudge.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      if (lc.includes('[redacted]')) {
        gates.sanitizer.count++
        gates.sanitizer.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      if (c.includes('[harness]') && lc.includes('cap') && (
        lc.includes('budget-cap') ||
        lc.includes('wall-clock cap') ||
        lc.includes('token cap') ||
        lc.includes('destructive-call cap') ||
        lc.includes('consecutive-tool-failure cap')
      )) {
        gates.forced_synthesis.count++
        gates.forced_synthesis.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
      // v2.35.2 — in-run cross-tool contradiction advisory
      if (c.includes('[harness] Contradiction detected within this run')) {
        gates.inrun_contradiction.count++
        gates.inrun_contradiction.details.push({ step: stepIdx, snippet: c.slice(0, 160) })
      }
    }
  }

  const fab = countFabrication(steps)
  if (fab) gates.fabrication.count = fab
  return gates
}
