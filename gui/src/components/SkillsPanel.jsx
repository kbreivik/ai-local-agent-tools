/**
 * SkillsPanel — browse and execute registered dynamic skills.
 */
import { useEffect, useState, useCallback } from 'react'
import { fetchSkills, executeSkill, promoteSkill, demoteSkill, scrapSkill, restoreSkill } from '../api'

const CATEGORY_COLOR = {
  compute:    'bg-blue-900 text-blue-300',
  networking: 'bg-green-900 text-green-300',
  storage:    'bg-purple-900 text-purple-300',
  monitoring: 'bg-teal-900 text-teal-300',
  general:    'bg-slate-700 text-slate-300',
}

function categoryBadge(cat) {
  return CATEGORY_COLOR[cat] ?? 'bg-slate-700 text-slate-400'
}

// ── Param form ────────────────────────────────────────────────────────────────

function ParamForm({ skill, onSubmit, onCancel, running }) {
  const props = skill.parameters?.properties ?? {}
  const required = skill.parameters?.required ?? []
  const [values, setValues] = useState(() =>
    Object.fromEntries(Object.keys(props).map(k => [k, '']))
  )

  const set = (k, v) => setValues(prev => ({ ...prev, [k]: v }))

  return (
    <div className="mt-2 border border-slate-600 rounded p-2 bg-slate-800 text-xs">
      {Object.entries(props).map(([k, schema]) => (
        <div key={k} className="mb-2">
          <label className="block text-slate-400 mb-0.5">
            {k}{required.includes(k) && <span className="text-red-400 ml-0.5">*</span>}
            {schema.description && (
              <span className="text-slate-600 ml-1">— {schema.description}</span>
            )}
          </label>
          <input
            value={values[k]}
            onChange={e => set(k, e.target.value)}
            placeholder={schema.type === 'integer' ? '0' : `${k}…`}
            className="w-full bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-200 focus:outline-none focus:border-blue-500"
          />
        </div>
      ))}
      <div className="flex gap-2 mt-1">
        <button
          onClick={() => onSubmit(values)}
          disabled={running}
          className="px-3 py-1 rounded bg-green-600 hover:bg-green-700 text-white disabled:bg-slate-700 disabled:text-slate-500"
        >
          {running ? '…' : 'Run'}
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}

// ── Result display ────────────────────────────────────────────────────────────

function ResultBox({ result }) {
  const ok = result?.status === 'ok'
  const border = ok ? 'border-green-700' : 'border-red-700'
  const text   = ok ? 'text-green-300'  : 'text-red-300'
  return (
    <div className={`mt-2 border ${border} rounded p-2 bg-slate-800 text-xs`}>
      <span className={`font-bold ${text}`}>{result?.status?.toUpperCase()}</span>
      {result?.message && (
        <span className="text-slate-400 ml-2">{result.message}</span>
      )}
      {result?.data && (
        <pre className="mt-1 text-slate-300 whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
          {JSON.stringify(result.data, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ── Skill card ────────────────────────────────────────────────────────────────

const DOMAINS = ['proxmox', 'swarm', 'kafka', 'general']

function LifecycleBadge({ state }) {
  if (state === 'promoted')
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900 text-green-300">promoted</span>
  if (state === 'scrapped')
    return <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900 text-red-300">scrapped</span>
  return null
}

function SkillCard({ skill, onReload }) {
  const [open,        setOpen]        = useState(false)
  const [running,     setRunning]     = useState(false)
  const [result,      setResult]      = useState(null)
  const [promoting,   setPromoting]   = useState(false)
  const [working,     setWorking]     = useState(false)

  const state     = skill.lifecycle_state ?? 'auto_generated'
  const hasParams = Object.keys(skill.parameters?.properties ?? {}).length > 0
  const tested    = result !== null
  const isEnabled = skill.enabled !== false && state !== 'scrapped'

  const handleExecute = () => {
    setResult(null)
    if (hasParams) setOpen(true)
    else run({})
  }

  const run = async (params) => {
    setRunning(true)
    setOpen(false)
    try {
      const props = skill.parameters?.properties ?? {}
      const cast = Object.fromEntries(
        Object.entries(params).map(([k, v]) => [
          k, props[k]?.type === 'integer' ? (parseInt(v, 10) || 0) : v,
        ])
      )
      const r = await executeSkill(skill.name, cast)
      setResult(r)
    } catch (e) {
      setResult({ status: 'error', message: e.message })
    } finally {
      setRunning(false)
    }
  }

  const handlePromote = async (domain) => {
    setWorking(true)
    try {
      await promoteSkill(skill.name, domain)
    } catch (e) {
      setResult({ status: 'error', message: `Promote failed: ${e.message}` })
    } finally {
      setPromoting(false)
      setWorking(false)
      onReload()
    }
  }

  const handleDemote = async () => {
    setWorking(true)
    try {
      await demoteSkill(skill.name)
    } catch (e) {
      setResult({ status: 'error', message: `Demote failed: ${e.message}` })
    } finally {
      setWorking(false)
      onReload()
    }
  }

  const handleScrap = async () => {
    setWorking(true)
    try {
      await scrapSkill(skill.name)
    } catch (e) {
      setResult({ status: 'error', message: `Scrap failed: ${e.message}` })
    } finally {
      setWorking(false)
      onReload()
    }
  }

  const handleRestore = async () => {
    setWorking(true)
    try {
      await restoreSkill(skill.name)
    } catch (e) {
      setResult({ status: 'error', message: `Restore failed: ${e.message}` })
    } finally {
      setWorking(false)
      onReload()
    }
  }

  return (
    <div className={`border rounded p-2 mb-2 bg-slate-900 ${
      state === 'promoted' ? 'border-green-800' :
      state === 'scrapped' ? 'border-red-900 opacity-60' :
      'border-slate-700'
    }`}>
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className={`font-mono text-xs ${state === 'scrapped' ? 'line-through text-slate-500' : 'text-slate-200'}`}>
              {skill.name}
            </span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${categoryBadge(skill.category)}`}>
              {skill.category}
            </span>
            {skill.auto_generated && state !== 'promoted' && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-900 text-amber-300">generated</span>
            )}
            <LifecycleBadge state={state} />
            {state === 'promoted' && skill.agent_domain && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">
                {skill.agent_domain}
              </span>
            )}
          </div>
          <p className="text-slate-400 text-xs mt-0.5 leading-snug">{skill.description}</p>
        </div>

        {/* Action buttons */}
        <div className="flex gap-1 shrink-0">
          {state === 'scrapped' ? (
            <button onClick={handleRestore} disabled={working}
              className="px-2 py-1 text-xs rounded bg-slate-600 hover:bg-slate-500 text-white disabled:opacity-40">
              {working ? '…' : '↺'}
            </button>
          ) : (
            <>
              <button onClick={handleExecute} disabled={running || !isEnabled}
                className="px-2 py-1 text-xs rounded bg-blue-700 hover:bg-blue-600 text-white disabled:bg-slate-700 disabled:text-slate-500">
                {running ? '…' : '▶'}
              </button>
              {state === 'promoted' ? (
                <button onClick={handleDemote} disabled={working}
                  className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 text-slate-300 disabled:opacity-40">
                  {working ? '…' : '↓'}
                </button>
              ) : (
                <>
                  <button onClick={() => setPromoting(p => !p)} disabled={!tested || working}
                    title={tested ? 'Promote to @mcp.tool()' : 'Run test first'}
                    className="px-2 py-1 text-xs rounded bg-green-800 hover:bg-green-700 text-green-300 disabled:bg-slate-700 disabled:text-slate-500">
                    {working ? '…' : '↑'}
                  </button>
                  <button onClick={handleScrap} disabled={!tested || working}
                    title={tested ? 'Scrap this skill' : 'Run test first'}
                    className="px-2 py-1 text-xs rounded bg-red-900 hover:bg-red-800 text-red-300 disabled:bg-slate-700 disabled:text-slate-500">
                    {working ? '…' : '✕'}
                  </button>
                </>
              )}
            </>
          )}
        </div>
      </div>

      {skill.call_count > 0 && (
        <p className="text-slate-600 text-[10px] mt-1">
          called {skill.call_count}×
          {skill.last_called_at && ` · ${new Date(skill.last_called_at).toLocaleString()}`}
        </p>
      )}

      {open && (
        <ParamForm skill={skill} onSubmit={run} onCancel={() => setOpen(false)} running={running} />
      )}

      {/* Domain picker for promote */}
      {promoting && (
        <div className="mt-2 border border-green-800 rounded p-2 bg-slate-800 text-xs">
          <p className="text-slate-400 mb-2">Add to which agent? (takes effect on restart)</p>
          <div className="flex gap-2 flex-wrap">
            {DOMAINS.map(d => (
              <button key={d} onClick={() => handlePromote(d)}
                className="px-3 py-1 rounded bg-slate-700 hover:bg-green-800 hover:text-green-300 text-slate-300">
                {d}
              </button>
            ))}
          </div>
          <button onClick={() => setPromoting(false)} className="mt-2 text-slate-500 text-[10px]">cancel</button>
        </div>
      )}

      {result && <ResultBox result={result} />}
    </div>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function SkillsPanel() {
  const [skills,   setSkills]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [error,    setError]    = useState(null)
  const [category, setCategory] = useState('all')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchSkills()
      setSkills(data)
    } catch (e) {
      setError('Failed to load skills')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const categories = ['all', ...new Set(skills.map(s => s.category))]
  const visible    = category === 'all' ? skills : skills.filter(s => s.category === category)

  return (
    <div className="flex flex-col h-full w-full bg-slate-950">
      <div className="px-4 py-2 border-b border-slate-700 bg-slate-900 shrink-0 flex items-center gap-3">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">Skills</span>
        <span className="text-slate-600 text-xs">
          {loading ? 'loading…' : `${skills.length} registered`}
        </span>
        <button
          onClick={load}
          className="ml-auto text-xs px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-300"
        >
          ↻ Refresh
        </button>
      </div>

      <div className="flex gap-1 px-4 py-2 border-b border-slate-700 flex-wrap shrink-0">
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${
              category === c
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {c === 'all' ? `All (${skills.length})` : c}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3">
        {loading && (
          <p className="text-xs text-slate-500 animate-pulse">Loading skills…</p>
        )}
        {error && (
          <p className="text-xs text-red-400">{error}</p>
        )}
        {!loading && !error && visible.length === 0 && (
          <p className="text-xs text-slate-600">
            No skills found.{' '}
            {category !== 'all' && (
              <button onClick={() => setCategory('all')} className="text-blue-400 underline">
                Show all
              </button>
            )}
          </p>
        )}
        {visible.map(skill => (
          <SkillCard key={skill.name} skill={skill} onReload={load} />
        ))}
      </div>
    </div>
  )
}
