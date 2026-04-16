import { describe, it, expect } from 'vitest'
import { INFRA_SECTION_KEYS, ALL_CARD_KEYS } from '../CardFilterBar'

// Platforms the backend currently emits as dashboard sections. Keep this
// synced with the SECTION_PLATFORMS map in App.jsx and the collector list
// in api/collectors/manager.py. If the backend adds a new platform and this
// test starts failing, add the corresponding section key to CardFilterBar.
const EXPECTED_SECTION_KEYS = [
  'vms',
  'containers_local',
  'containers_swarm',
  'unifi',
  'fortigate',
  'pbs',
  'truenas',
]

describe('CardFilterBar section-key sync', () => {
  it('every expected backend platform has a section key', () => {
    const keys = INFRA_SECTION_KEYS.map(c => c.key)
    const missing = EXPECTED_SECTION_KEYS.filter(k => !keys.includes(k))
    expect(missing).toEqual([])
  })

  it('ALL_CARD_KEYS has no duplicate keys', () => {
    const keys = ALL_CARD_KEYS.map(c => c.key)
    const unique = new Set(keys)
    expect(keys.length).toEqual(unique.size)
  })

  it('every ALL_CARD_KEYS entry has key + label', () => {
    for (const c of ALL_CARD_KEYS) {
      expect(c.key).toBeTruthy()
      expect(c.label).toBeTruthy()
    }
  })
})
