/**
 * useLayout — per-user dashboard layout hook.
 * Loads layout from server on mount, provides mutation helpers,
 * tracks dirty state, and exposes saveLayout() for persistence.
 */
import { useState, useEffect, useCallback } from 'react'
import { authHeaders } from '../api'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export const DEFAULT_LAYOUT = {
  template: 'DEFAULT',
  rows: [
    { tiles: ['PLATFORM'], heightMode: 'auto' },
    { tiles: ['COMPUTE', 'CONTAINERS'], flex: [3, 2], heightMode: 'auto' },
    { tiles: ['NETWORK'], heightMode: 'auto' },
    { tiles: ['STORAGE', 'SECURITY'], heightMode: 'auto' },
  ],
  collapsed: [],
  prefs: {
    drill_persist: true,
    density: 'compact',
    compare_on_load: false,
  },
}

export function useLayout() {
  const [layout, setLayout] = useState(DEFAULT_LAYOUT)
  const [dirty, setDirty] = useState(false)
  const [loaded, setLoaded] = useState(false)

  // Load on mount
  useEffect(() => {
    fetch(`${BASE}/api/users/me/layout`, { headers: { ...authHeaders() } })
      .then(r => r.json())
      .then(d => {
        if (d.layout_json) {
          try {
            setLayout(JSON.parse(d.layout_json))
          } catch { /* use default */ }
        }
        setLoaded(true)
      })
      .catch(() => setLoaded(true))
  }, [])

  const saveLayout = useCallback((l) => {
    const target = l || layout
    fetch(`${BASE}/api/users/me/layout`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ layout_json: JSON.stringify(target) }),
    }).catch(() => {})
    setDirty(false)
  }, [layout])

  const updateRows = useCallback((rows) => {
    setLayout(l => ({ ...l, rows }))
    setDirty(true)
  }, [])

  const toggleCollapse = useCallback((tile) => {
    setLayout(l => {
      const collapsed = l.collapsed.includes(tile)
        ? l.collapsed.filter(t => t !== tile)
        : [...l.collapsed, tile]
      return { ...l, collapsed }
    })
    setDirty(true)
  }, [])

  const setPrefs = useCallback((prefs) => {
    setLayout(l => ({ ...l, prefs: { ...l.prefs, ...prefs } }))
    setDirty(true)
  }, [])

  const applyTemplate = useCallback((templateLayout) => {
    setLayout(templateLayout)
    setDirty(true)
  }, [])

  return { layout, loaded, dirty, saveLayout, updateRows, toggleCollapse, setPrefs, applyTemplate, setLayout }
}
