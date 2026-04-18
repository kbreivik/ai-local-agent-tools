import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import FactsView from '../FactsView'
import FactsCard from '../FactsCard'

// ── Minimal fetch mock matched by URL pattern ───────────────────────────────

function installFetch(routes) {
  global.fetch = vi.fn((url, opts = {}) => {
    const path = String(url).replace(/^https?:\/\/[^/]+/, '')
    for (const [pattern, handler] of routes) {
      const m = path.match(pattern)
      if (m) {
        const body = handler({ url: path, method: opts.method || 'GET', m, opts })
        return Promise.resolve({
          ok: body.ok !== false,
          status: body.status || 200,
          statusText: body.statusText || 'OK',
          text: () => Promise.resolve(JSON.stringify(body.data ?? {})),
          json: () => Promise.resolve(body.data ?? {}),
        })
      }
    }
    return Promise.resolve({
      ok: false, status: 404, statusText: 'Not found',
      text: () => Promise.resolve(''),
      json: () => Promise.resolve({}),
    })
  })
}

beforeEach(() => {
  localStorage.clear()
})

describe('FactsView', () => {
  it('renders a list of facts and filters by pattern', async () => {
    const facts = [
      { fact_key: 'prod.kafka.broker.1.host', source: 'kafka_collector', confidence: 0.92, last_verified: new Date().toISOString(), change_detected: false, fact_value: '192.168.199.31' },
      { fact_key: 'prod.swarm.service.web.placement', source: 'swarm_collector', confidence: 0.85, last_verified: new Date().toISOString(), change_detected: false, fact_value: 'worker-01' },
    ]
    installFetch([
      [/\/api\/facts\?/, () => ({ data: { facts, count: facts.length } })],
      [/\/api\/facts\/conflicts$/, () => ({ data: { conflicts: [] } })],
      [/\/api\/facts\/locks$/, () => ({ data: { locks: [] } })],
    ])

    render(<FactsView userRole="sith_lord" />)

    await waitFor(() => {
      expect(screen.getByTestId('facts-view')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.queryByTestId('fact-row-prod.kafka.broker.1.host')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('fact-row-prod.swarm.service.web.placement')).toBeInTheDocument()
  })

  it('shows conflict banner when pending conflicts exist', async () => {
    installFetch([
      [/\/api\/facts\?/, () => ({ data: { facts: [], count: 0 } })],
      [/\/api\/facts\/conflicts$/, () => ({ data: { conflicts: [
        { id: 1, fact_key: 'prod.x', locked_value: 'a', offered_source: 's', offered_value: 'b', offered_at: new Date().toISOString() },
      ] } })],
      [/\/api\/facts\/locks$/, () => ({ data: { locks: [] } })],
    ])

    render(<FactsView userRole="imperial_officer" />)

    await waitFor(() => {
      expect(screen.queryByTestId('conflict-banner')).toBeInTheDocument()
    })
  })

  it('lock button is disabled for non-admin', async () => {
    installFetch([
      [/\/api\/facts\?/, () => ({ data: {
        facts: [{ fact_key: 'prod.x', source: 'col', confidence: 0.9, last_verified: new Date().toISOString(), change_detected: false, fact_value: 'v' }],
        count: 1,
      }})],
      [/\/api\/facts\/conflicts$/, () => ({ data: { conflicts: [] } })],
      [/\/api\/facts\/locks$/, () => ({ data: { locks: [] } })],
      [/\/api\/facts\/key\//, () => ({ data: {
        fact_key: 'prod.x',
        sources: [{ source: 'col', fact_value: 'v', confidence: 0.9, last_verified: new Date().toISOString(), verify_count: 3 }],
        history: [],
        lock: null,
      }})],
    ])

    render(<FactsView userRole="imperial_officer" />)

    await waitFor(() => {
      expect(screen.getByTestId('fact-row-prod.x')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('fact-row-prod.x'))

    await waitFor(() => {
      const btn = screen.getByTestId('lock-fact-btn')
      expect(btn).toBeDisabled()
    })
  })
})

describe('FactsCard dashboard widget', () => {
  it('renders counts and shows pending badge when conflicts > 0', async () => {
    installFetch([
      [/\/api\/facts\/summary$/, () => ({ data: {
        total: 842, by_tier: { very_high: 408, high: 204, medium: 89, low: 50, reject: 91 },
        pending_conflicts: 2, last_refresh: new Date().toISOString(), recently_changed: [],
      } })],
      [/\/api\/facts\/stale$/,   () => ({ data: { stale: [] } })],
      [/\/api\/facts\/changed/,  () => ({ data: { changes: [] } })],
    ])

    render(<FactsCard />)

    await waitFor(() => {
      expect(screen.getByTestId('facts-card')).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByTestId('pending-badge')).toBeInTheDocument()
    })
    expect(screen.getByTestId('facts-card').textContent).toContain('842')
  })
})
