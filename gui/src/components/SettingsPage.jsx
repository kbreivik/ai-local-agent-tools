/**
 * SettingsPage — full-page settings view (replaces modal).
 * Reuses tab components from OptionsModal.
 */
import { useState, useEffect } from 'react'
import { useOptions } from '../context/OptionsContext'
import { authHeaders } from '../api'
// Import tab components — they are defined in OptionsModal.jsx but we re-export them
import {
  GeneralTab, InfrastructureTab, AIServicesTab,
  ConnectionsTab, AllowlistTab, PermissionsTab, AccessTab, NamingTab,
  DisplayTab, NotificationsTab, FactsKnowledgeTab, UpdateStatus, TABS,
} from './OptionsModal'
import LayoutsTab from './LayoutsTab'
import FactsPermissionsTab from './FactsPermissionsTab'

const BASE = import.meta.env.VITE_API_BASE ?? ''

export default function SettingsPage({ initialTab, layoutState, userRole }) {
  const options = useOptions()
  const { serverLoaded } = options
  const [tab, setTab] = useState(initialTab || 'General')

  // Sync tab when sidebar changes the initialTab prop
  useEffect(() => {
    if (initialTab) setTab(initialTab)
  }, [initialTab])
  const [draft, setDraft] = useState(null)
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState('')

  const LIVE_KEYS = ['cardMinHeight', 'cardMaxHeight', 'cardMinWidth', 'cardMaxWidth']

  // Initialize draft from current options on mount
  useEffect(() => {
    setDraft({ ...options })
  }, [serverLoaded]) // eslint-disable-line react-hooks/exhaustive-deps

  const update = (key, value) => {
    setDraft(prev => prev ? { ...prev, [key]: value } : prev)
    if (LIVE_KEYS.includes(key)) {
      options.setOption(key, value)
    }
  }

  const save = async () => {
    if (!draft) return
    setSaving(true)
    setSaveMsg('')
    try {
      await options.saveOptions(draft)
      setSaveMsg('Settings saved')
      setTimeout(() => setSaveMsg(''), 2000)
    } catch (e) {
      setSaveMsg(e.message || 'Failed to save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header + tabs */}
      <div className="px-5 pt-4 pb-0 shrink-0">
        <h1 className="text-sm font-semibold mb-3" style={{ color: 'var(--text-1)' }}>Settings</h1>
        <div className="flex border-b overflow-x-auto" style={{ borderColor: 'var(--border)', scrollbarWidth: 'none' }}>
          {TABS.map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-[11px] font-medium transition-colors border-b-2 ${
                tab === t
                  ? 'border-blue-500 text-blue-400'
                  : 'border-transparent hover:text-[color:var(--text-1)]'
              }`}
              style={tab !== t ? { color: 'var(--text-3)' } : undefined}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto px-5 py-4" style={{ overflowX: 'hidden' }}>
        {!serverLoaded && (tab === 'Infrastructure' || tab === 'AI Services') && (
          <p className="text-xs animate-pulse mb-3" style={{ color: 'var(--text-3)' }}>Loading from server…</p>
        )}
        {draft && (
          <>
            {tab === 'General'        && <GeneralTab        draft={draft} update={update} />}
            {tab === 'Infrastructure' && <InfrastructureTab draft={draft} update={update} />}
            {tab === 'AI Services'    && <AIServicesTab     draft={draft} update={update} />}
            {tab === 'Connections'    && <ConnectionsTab />}
            {tab === 'Permissions'    && <PermissionsTab />}
            {tab === 'Facts Permissions' && <FactsPermissionsTab userRole={userRole} />}
            {tab === 'Facts & Knowledge' && <FactsKnowledgeTab draft={draft} update={update} />}
            {tab === 'Access'        && <AccessTab />}
            {tab === 'Naming'        && <NamingTab         draft={draft} update={update} />}
            {(tab === 'Appearance' || tab === 'Display') && <DisplayTab draft={draft} update={update} />}
            {tab === 'Allowlist'     && <AllowlistTab />}
            {tab === 'Notifications' && <NotificationsTab  draft={draft} update={update} />}
            {tab === 'Layouts'       && layoutState && (
              <LayoutsTab
                layout={layoutState.layout}
                dirty={layoutState.dirty}
                saveLayout={layoutState.saveLayout}
                applyTemplate={layoutState.applyTemplate}
                setLayout={layoutState.setLayout}
              />
            )}
            {tab === 'Layouts' && !layoutState && (
              <div style={{ fontSize: 10, color: 'var(--text-3)', padding: 16 }}>
                Layout settings are only available from the Dashboard.
              </div>
            )}
          </>
        )}
      </div>

      {/* Footer — save button (hidden on Connections tab) */}
      {!['Connections', 'Allowlist', 'Permissions', 'Facts Permissions', 'Access', 'Layouts'].includes(tab) && (
        <div className="flex items-center justify-end gap-3 px-5 py-3 border-t shrink-0" style={{ borderColor: 'var(--border)' }}>
          {saveMsg && (
            <span className={`text-xs mr-auto ${saveMsg.includes('saved') ? 'text-green-400' : 'text-red-400'}`}>{saveMsg}</span>
          )}
          <button
            onClick={save}
            disabled={saving}
            className="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold rounded transition-colors disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      )}
    </div>
  )
}
