import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { fetchSettings, saveSettings } from '../api'

const STORAGE_KEY = 'hp1_options'

const DEFAULTS = {
  // General
  theme:                    'dark',
  dashboardRefreshInterval: 15000,
  autoUpdate:               false,

  // Infrastructure
  dockerHost:             '',
  swarmManagerIPs:        '',
  swarmWorkerIPs:         '',
  ghcrToken:              '',
  agentDockerHost:        '',
  kafkaBootstrapServers:  '',
  elasticsearchUrl:       '',
  kibanaUrl:              '',
  muninndbUrl:            '',

  // Infrastructure credentials
  proxmoxHost:         '',
  proxmoxTokenId:      '',
  proxmoxTokenSecret:  '',
  proxmoxUser:         'root@pam',
  proxmoxNodes:        '',
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

  // v2.36.x — External AI Router
  externalRoutingMode:               'off',      // 'off'|'manual'|'auto'
  externalRoutingOutputMode:         'replace',
  routeOnGateFailure:                true,
  routeOnBudgetExhaustion:           true,
  routeOnConsecutiveFailures:        3,
  routeOnPriorAttemptsGte:           0,
  routeOnComplexityKeywords:         '',
  routeOnComplexityMinPriorAttempts: 2,
  routeMaxExternalCallsPerOp:        3,
  externalConfirmTimeoutSeconds:     300,
  externalContextLastNToolResults:   5,

  // Facts & Knowledge (v2.35.0 – v2.35.4 — v2.36.6 allowlisted)
  factInjectionThreshold:            0.7,
  factInjectionMaxRows:              40,
  factSourceWeight_manual:                 1.0,
  factSourceWeight_proxmox_collector:      0.9,
  factSourceWeight_swarm_collector:        0.9,
  factSourceWeight_docker_agent_collector: 0.85,
  factSourceWeight_pbs_collector:          0.85,
  factSourceWeight_kafka_collector:        0.8,
  factSourceWeight_fortiswitch_collector:  0.85,
  factSourceWeight_agent_observation:      0.5,
  factSourceWeight_rag_extraction:         0.4,
  factHalfLifeHours_collector:       168,
  factHalfLifeHours_agent:           24,
  factHalfLifeHours_manual_phase1:   720,
  factHalfLifeHours_manual_phase2:   1440,
  factHalfLifeHours_agent_volatile:  2,
  factVerifyCountCap:                10,
  factAgeRejectionMode:              'medium',
  factAgeRejectionMaxAgeMin:         5,
  factAgeRejectionMinConfidence:     0.85,
  runbookInjectionMode:              'augment',
  runbookClassifierMode:             'keyword',
  preflightPanelMode:                'always_visible',
  preflightDisambiguationTimeout:    300,
  preflightLLMFallbackEnabled:       true,
  preflightLLMFallbackMaxTokens:     200,

  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  agentToolBudget_observe:     8,
  agentToolBudget_investigate: 16,
  agentToolBudget_execute:     14,
  agentToolBudget_build:       12,

  // Coordinator
  coordinatorPriorAttemptsEnabled: true,

  // Display (localStorage only)
  cardMinHeight:        70,
  cardMaxHeight:        200,
  cardMinWidth:         300,
  cardMaxWidth:         null,
  nodeCardSize:         'medium',
  showVersionBadges:    true,
  showMemoryEngrams:    true,
  commandsPanelDefault: 'hidden',

  // Appearance — visual tuning (localStorage only)
  accentColor:    'crimson',   // 'crimson'|'blue'|'purple'|'teal'|'orange'|'green'
  fontSize:       'medium',    // 'small'|'medium'|'large'
  uiDensity:      'normal',    // 'compact'|'normal'|'comfortable'
  borderRadius:   'sharp',     // 'sharp'|'soft'|'round'
  fontStyle:      'mono',      // 'mono'|'mixed'|'sans'
}

// Keys managed by the server. Only these are sent to / fetched from the API.
// Keys persisted to POST /api/settings.
// Service connections (proxmox, fortigate, truenas) are managed via Connections tab → /api/connections.
const SERVER_KEYS = new Set([
  'lmStudioUrl', 'lmStudioApiKey', 'modelName',
  'externalProvider', 'externalApiKey', 'externalModel',
  'autoEscalate', 'requireConfirmation',
  'externalRoutingMode', 'externalRoutingOutputMode',
  'routeOnGateFailure', 'routeOnBudgetExhaustion', 'routeOnConsecutiveFailures',
  'routeOnPriorAttemptsGte', 'routeOnComplexityKeywords',
  'routeOnComplexityMinPriorAttempts',
  'routeMaxExternalCallsPerOp', 'externalConfirmTimeoutSeconds',
  'externalContextLastNToolResults',
  'coordinatorPriorAttemptsEnabled',
  'kafkaBootstrapServers', 'elasticsearchUrl', 'kibanaUrl',
  'muninndbUrl', 'dockerHost', 'swarmManagerIPs', 'swarmWorkerIPs', 'ghcrToken', 'agentDockerHost',
  'autoUpdate', 'dashboardRefreshInterval',
  // Facts & Knowledge (v2.35.0 – v2.35.4 — v2.36.6 allowlisted)
  'factInjectionThreshold', 'factInjectionMaxRows',
  'factSourceWeight_manual', 'factSourceWeight_proxmox_collector',
  'factSourceWeight_swarm_collector', 'factSourceWeight_docker_agent_collector',
  'factSourceWeight_pbs_collector', 'factSourceWeight_kafka_collector',
  'factSourceWeight_fortiswitch_collector', 'factSourceWeight_agent_observation',
  'factSourceWeight_rag_extraction',
  'factHalfLifeHours_collector', 'factHalfLifeHours_agent',
  'factHalfLifeHours_manual_phase1', 'factHalfLifeHours_manual_phase2',
  'factHalfLifeHours_agent_volatile',
  'factVerifyCountCap',
  'factAgeRejectionMode', 'factAgeRejectionMaxAgeMin', 'factAgeRejectionMinConfidence',
  'runbookInjectionMode', 'runbookClassifierMode',
  'preflightPanelMode', 'preflightDisambiguationTimeout',
  'preflightLLMFallbackEnabled', 'preflightLLMFallbackMaxTokens',

  // Agent Budgets (v2.36.5 — v2.36.6 allowlisted)
  'agentToolBudget_observe', 'agentToolBudget_investigate',
  'agentToolBudget_execute', 'agentToolBudget_build',
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
        // Write agentHostIp to window for EntityDrawer accessibility display
        if (serverData.agentHostIp) {
          window.__agentHostIp = serverData.agentHostIp
        }
        setServerLoaded(true)
      })
      .catch(() => {
        // Server unreachable — continue with localStorage values
        setServerLoaded(true)
      })
  }, [])

  useEffect(() => { loadFromServer() }, [loadFromServer])

  // Sync data-theme attribute on <html> for CSS custom properties
  useEffect(() => {
    const theme = options.theme || 'dark'
    if (theme === 'system') {
      document.documentElement.removeAttribute('data-theme')
    } else {
      document.documentElement.setAttribute('data-theme', theme)
    }
  }, [options.theme])

  // Apply tunable CSS vars from appearance settings
  useEffect(() => {
    const root = document.documentElement

    // Accent color presets
    const ACCENTS = {
      crimson: { accent: '#a01828', accentDim: 'rgba(160,24,40,0.12)', accentHover: '#b81e2e' },
      blue:    { accent: '#1a56e8', accentDim: 'rgba(26,86,232,0.12)',  accentHover: '#2563eb' },
      purple:  { accent: '#7c3aed', accentDim: 'rgba(124,58,237,0.12)', accentHover: '#8b5cf6' },
      teal:    { accent: '#0891b2', accentDim: 'rgba(8,145,178,0.12)',  accentHover: '#0ea5e9' },
      orange:  { accent: '#c2410c', accentDim: 'rgba(194,65,12,0.12)',  accentHover: '#ea580c' },
      green:   { accent: '#047857', accentDim: 'rgba(4,120,87,0.12)',   accentHover: '#059669' },
    }
    const a = ACCENTS[options.accentColor] || ACCENTS.crimson
    root.style.setProperty('--accent', a.accent)
    root.style.setProperty('--accent-dim', a.accentDim)
    root.style.setProperty('--accent-hover', a.accentHover)

    // Font size
    const FONT_SIZES = { small: '11px', medium: '13px', large: '15px' }
    root.style.setProperty('--font-size-base', FONT_SIZES[options.fontSize] || '13px')

    // UI density
    const DENSITY = {
      compact:     { gap: '3px', pad: '4px',  padLg: '7px'  },
      normal:      { gap: '5px', pad: '6px',  padLg: '10px' },
      comfortable: { gap: '8px', pad: '9px',  padLg: '14px' },
    }
    const d = DENSITY[options.uiDensity] || DENSITY.normal
    root.style.setProperty('--density-gap', d.gap)
    root.style.setProperty('--density-pad', d.pad)
    root.style.setProperty('--density-pad-lg', d.padLg)

    // Border radius
    const RADII = {
      sharp: { card: '2px', btn: '2px', pill: '2px' },
      soft:  { card: '4px', btn: '4px', pill: '8px' },
      round: { card: '8px', btn: '6px', pill: '12px' },
    }
    const r = RADII[options.borderRadius] || RADII.sharp
    root.style.setProperty('--radius-card', r.card)
    root.style.setProperty('--radius-btn', r.btn)
    root.style.setProperty('--radius-pill', r.pill)

    // Font style
    const FONTS = {
      mono:  "'Share Tech Mono', monospace",
      mixed: "'Rajdhani', sans-serif",
      sans:  "'Inter', sans-serif",
    }
    root.style.setProperty('--font-ui', FONTS[options.fontStyle] || FONTS.mono)
  }, [options.accentColor, options.fontSize, options.uiDensity, options.borderRadius, options.fontStyle])

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

    // Persist server-owned keys to API — exclude masked values and empty secrets
    const SENSITIVE = new Set(['lmStudioApiKey', 'externalApiKey', 'proxmoxTokenSecret', 'ghcrToken', 'fortigateApiKey', 'truenasApiKey'])
    const serverPayload = Object.fromEntries(
      Object.entries(merged).filter(([k, v]) => {
        if (!SERVER_KEYS.has(k)) return false
        if (isMasked(v)) return false
        // Don't send empty strings for sensitive keys — preserves existing DB value
        if (SENSITIVE.has(k) && (v === '' || v == null)) return false
        return true
      })
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
