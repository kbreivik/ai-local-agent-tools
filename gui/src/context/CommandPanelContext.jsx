import { createContext, useContext, useState, useEffect } from 'react'

const CommandPanelContext = createContext(null)

export function CommandPanelProvider({ defaultOpen = false, children }) {
  const [panelOpen, setPanelOpen] = useState(defaultOpen)

  const togglePanel = () => setPanelOpen(o => !o)
  const openPanel   = () => setPanelOpen(true)
  const closePanel  = () => setPanelOpen(false)

  // Ctrl+Shift+C global shortcut
  useEffect(() => {
    const handler = (e) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'C') {
        e.preventDefault()
        togglePanel()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])   // togglePanel is stable enough — no need to re-register

  return (
    <CommandPanelContext.Provider value={{ panelOpen, togglePanel, openPanel, closePanel }}>
      {children}
    </CommandPanelContext.Provider>
  )
}

export function useCommandPanel() {
  const ctx = useContext(CommandPanelContext)
  if (!ctx) throw new Error('useCommandPanel must be used inside CommandPanelProvider')
  return ctx
}
