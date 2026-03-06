import { createContext, useContext, useState, useEffect, useCallback } from 'react'

const AgentContext = createContext(null)

export function AgentProvider({ children }) {
  const [agentState, setAgentState] = useState(null) // null | 'running' | 'success' | 'failed'

  const markRunning = useCallback(() => setAgentState('running'), [])
  const markDone    = useCallback((ok) => setAgentState(ok ? 'success' : 'failed'), [])
  const clearState  = useCallback(() => setAgentState(null), [])

  // Auto-clear success/failed badge after 30 s
  useEffect(() => {
    if (agentState === 'success' || agentState === 'failed') {
      const id = setTimeout(clearState, 30_000)
      return () => clearTimeout(id)
    }
  }, [agentState, clearState])

  return (
    <AgentContext.Provider value={{ agentState, markRunning, markDone, clearState }}>
      {children}
    </AgentContext.Provider>
  )
}

export function useAgent() {
  const ctx = useContext(AgentContext)
  if (!ctx) throw new Error('useAgent must be used inside AgentProvider')
  return ctx
}
