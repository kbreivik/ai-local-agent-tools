/**
 * useCardTemplate — resolves the effective card template for a given card type
 * and optional connection ID. Fetches from /api/card-templates with a simple
 * in-memory cache (30s TTL) to avoid per-card API calls.
 */
import { useState, useEffect } from 'react'
import { authHeaders } from '../api'
import { DEFAULT_TEMPLATES } from '../schemas/cardSchemas'

const BASE = import.meta.env.VITE_API_BASE ?? ''
const _cache = new Map()   // key → {data, expires}
const TTL_MS = 30_000

async function _fetchTemplate(cardType, connectionId) {
  const cacheKey = connectionId ? `conn:${connectionId}` : `type:${cardType}`
  const cached = _cache.get(cacheKey)
  if (cached && cached.expires > Date.now()) return cached.data

  try {
    // Fetch type default first — cheap and always available
    const typeKey = `type:${cardType}`
    if (!_cache.get(typeKey) || _cache.get(typeKey).expires <= Date.now()) {
      const r = await fetch(`${BASE}/api/card-templates/type/${cardType}`, {
        headers: authHeaders(),
      })
      if (r.ok) {
        const d = await r.json()
        _cache.set(typeKey, { data: d.template, expires: Date.now() + TTL_MS })
      }
    }

    // Check per-connection override
    if (connectionId) {
      const r = await fetch(`${BASE}/api/card-templates/connection/${connectionId}`, {
        headers: authHeaders(),
      })
      if (r.ok) {
        const d = await r.json()
        if (d.has_override && d.template) {
          _cache.set(cacheKey, { data: d.template, expires: Date.now() + TTL_MS })
          return d.template
        }
      }
      // No override — use type default
      const typeCached = _cache.get(typeKey)
      if (typeCached?.data) {
        _cache.set(cacheKey, { data: typeCached.data, expires: Date.now() + TTL_MS })
        return typeCached.data
      }
    }

    const typeCached = _cache.get(typeKey)
    return typeCached?.data || null
  } catch {
    return null
  }
}

export function useCardTemplate(cardType, connectionId = null) {
  const [template, setTemplate] = useState(DEFAULT_TEMPLATES[cardType] || {})

  useEffect(() => {
    let cancelled = false
    _fetchTemplate(cardType, connectionId).then(t => {
      if (!cancelled && t) setTemplate(t)
    })
    return () => { cancelled = true }
  }, [cardType, connectionId])

  return template
}

/** Invalidate cache for a connection (call after saving a template override). */
export function invalidateCardTemplateCache(connectionId) {
  _cache.delete(`conn:${connectionId}`)
}

/** Invalidate type-level cache. */
export function invalidateCardTypeCache(cardType) {
  _cache.delete(`type:${cardType}`)
  // Also invalidate any connection caches that may use this type
  for (const key of _cache.keys()) {
    if (key.startsWith('conn:')) _cache.delete(key)
  }
}
