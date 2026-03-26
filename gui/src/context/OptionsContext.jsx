import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { fetchSettings, saveSettings } from '../api'

const STORAGE_KEY = 'hp1_options'

const DEFAULTS = {
  // General
  theme:                    'dark',
  dashboardRefreshInterval: 15000,

  // Infrastructure
  swarmManagerIPs:        '',
  swarmWorkerIPs:         '',
  dockerHost:             '',
  kafkaBootstrapServers:  '',
  elasticsearchUrl:       '',
  kibanaUrl:              '',
  muninndbUrl:            '',

  // Infrastructure credentials
  proxmoxHost:         '',
  proxmoxTokenId:      '',
  proxmoxTokenSecret:  '',
  fortigateHost:       '',
  fortigateApiKey:     '',
  truenasHost:         '',
  truenasApiKey:       '',

  // AI Services — Local
  lmStudioUrl:    '',
  lmStudioApiKey: '',
  modelName:      '',

  // AI Services — External
  externalProvider:    'claude',
  externalApiKey:      '',
  externalModel:       'claude-sonnet-4-6',

  // Escalation policy
  autoEscalate:        'both',
  requireConfirmation: true,

  // Display (localStorage only)
  cardMinHeight:        70,
  cardMaxHeight:        200,
  cardMinWidth:         300,
  cardMaxWidth:         null,
  nodeCardSize:         'medium',
  showVersionBadges:    true,
  showMemoryEngrams:    true,
  commandsPanelDefault: 'hidden',
}

// Keys managed by the server. Only these are sent to / fetched from the API.
const SERVER_KEYS = new Set([
  'lmStudioUrl', 'lmStudioApiKey', 'modelName',
  'externalProvider', 'externalApiKey', 'externalModel',
  'autoEscalate', 'requireConfirmation',
  'kafkaBootstrapServers', 'elasticsearchUrl', 'kibanaUrl',
  'muninndbUrl', 'dockerHost', 'swarmManagerIPs', 'swarmWorkerIPs',
  'dashboardRefreshInterval',
  'proxmoxHost', 'proxmoxTokenId', 'proxmoxTokenSecret',
  'fortigateHost', 'fortigateApiKey',
  'truenasHost', 'truenasApiKey',
])

function isMasked(v) {
  return typeof v === 'string' && v.includes('***')
}

const OptionsContext = createContext(null)

export function OptionsProvider({ children }) {
  const [options, setOptions] = useState(() => {
    try {
      const saved  = localStorage.getItem(STORAGE_KEY)
      const parsed = saved ? JSON.parse(saved) : {}
      return { ...DEFAULTS, ...parsed }
    } catch {
      return { ...DEFAULTS }
    }
  })
  const [serverLoaded, setServerLoaded] = useState(false)

  // Load server settings once on mount (after auth token is available)
  const loadFromServer = useCallback(() => {
    fetchSettings()
      .then(serverData => {
        setOptions(prev => {
          const merged = { ...prev }
          for (const [key, val] of Object.entries(serverData)) {
            // Don't overwrite a real local value with a masked server value
            if (isMasked(val) && prev[key]) continue
            merged[key] = val
          }
          return merged
        })
        setServerLoaded(true)
      })
      .catch(() => {
        // Server unreachable — continue with localStorage values
        setServerLoaded(true)
      })
  }, [])

  useEffect(() => { loadFromServer() }, [loadFromServer])

  const setOption = (key, value) => {
    setOptions(prev => ({ ...prev, [key]: value }))
  }

  const saveOptions = async (newOptions) => {
    const dataOnly = Object.fromEntries(
      Object.entries(newOptions).filter(([, v]) => typeof v !== 'function')
    )
    const merged = { ...DEFAULTS, ...options, ...dataOnly }
    setOptions(merged)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged))

    // Persist server-owned keys to API — exclude masked values to avoid overwriting real secrets
    const serverPayload = Object.fromEntries(
      Object.entries(merged).filter(([k, v]) => SERVER_KEYS.has(k) && !isMasked(v))
    )
    await saveSettings(serverPayload)  // throws on failure — let caller handle
  }

  const resetOptions = () => {
    setOptions({ ...DEFAULTS })
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <OptionsContext.Provider value={{
      ...options,
      serverLoaded,
      setOption,
      saveOptions,
      resetOptions,
      reloadFromServer: loadFromServer,
    }}>
      {children}
    </OptionsContext.Provider>
  )
}

export function useOptions() {
  const ctx = useContext(OptionsContext)
  if (!ctx) throw new Error('useOptions must be used inside OptionsProvider')
  return ctx
}
