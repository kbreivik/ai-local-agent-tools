import { createContext, useContext, useState, useEffect } from 'react'

const STORAGE_KEY = 'hp1_options'

const DEFAULTS = {
  // General
  theme:                    'dark',
  dashboardRefreshInterval: 15000,

  // Infrastructure
  swarmManagerIPs:        '',
  swarmWorkerIPs:         '',
  dockerHost:             'npipe:////./pipe/docker_engine',
  kafkaBootstrapServers:  'localhost:9092,localhost:9093,localhost:9094',
  elasticsearchUrl:       '',
  kibanaUrl:              '',
  muninndbUrl:            '',

  // AI Services — Local
  lmStudioUrl:   'http://localhost:1234/v1',
  lmStudioApiKey: '',
  modelName:     '',

  // AI Services — External
  externalProvider:      'claude',
  externalApiKey:        '',
  externalModel:         '',

  // Escalation policy
  autoEscalate:          'both',
  requireConfirmation:   true,

  // Display
  cardMinHeight:           120,
  cardMaxHeight:           280,
  nodeCardSize:            'medium',
  showVersionBadges:       true,
  showMemoryEngrams:       true,
  commandsPanelDefault:    'hidden',
}

const OptionsContext = createContext(null)

export function OptionsProvider({ children }) {
  const [options, setOptions] = useState(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY)
      return saved ? { ...DEFAULTS, ...JSON.parse(saved) } : { ...DEFAULTS }
    } catch {
      return { ...DEFAULTS }
    }
  })

  const setOption = (key, value) => {
    setOptions(prev => ({ ...prev, [key]: value }))
  }

  const saveOptions = (newOptions) => {
    const merged = { ...options, ...newOptions }
    setOptions(merged)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(merged))
  }

  const resetOptions = () => {
    setOptions({ ...DEFAULTS })
    localStorage.removeItem(STORAGE_KEY)
  }

  return (
    <OptionsContext.Provider value={{ ...options, setOption, saveOptions, resetOptions }}>
      {children}
    </OptionsContext.Provider>
  )
}

export function useOptions() {
  const ctx = useContext(OptionsContext)
  if (!ctx) throw new Error('useOptions must be used inside OptionsProvider')
  return ctx
}
