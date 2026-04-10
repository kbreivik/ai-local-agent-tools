/**
 * ComparePanel — right-side panel showing up to 4 selected entities
 * with per-entity chat threads and a broadcast row.
 */
import { useState, useRef, useEffect } from 'react'
import { askAgent } from '../api'

export const SLOT_COLORS = ['#00aa44','#00c8ee','#cc8800','#7c6af7']

/**
 * Derive 2-3 context-aware question suggestions for a compare slot.
 * Based on platform, status, and available metadata fields.
 */
function getEntitySuggestions(entity) {
  const { platform, status, metadata = {} } = entity
  const suggestions = []

  if (platform === 'proxmox') {
    const type = metadata.type === 'lxc' ? 'container' : 'VM'
    if (status === 'error' || metadata.status === 'stopped') {
      suggestions.push(`Why is this ${type} stopped?`)
      suggestions.push(`What are the resource requirements for ${entity.label}?`)
    } else if (status === 'degraded') {
      const pct = metadata.cpu_pct != null ? `CPU at ${metadata.cpu_pct}%` : null
      suggestions.push(pct ? `${pct} — is this normal?` : `Why is this ${type} degraded?`)
      suggestions.push(`Check disk usage on ${entity.label}`)
    } else {
      suggestions.push(`Summarise the health of ${entity.label}`)
      suggestions.push(`What services run on this ${type}?`)
    }
    if (metadata.node) suggestions.push(`Which node is ${entity.label} on and is it healthy?`)
  } else if (platform === 'unifi') {
    const devType = metadata.type || 'device'
    if (status === 'degraded' || metadata.state === 'disconnected') {
      suggestions.push(`Why is ${entity.label} disconnected?`)
      suggestions.push(`When did ${entity.label} last go offline?`)
    } else {
      if (metadata.clients != null) suggestions.push(`${metadata.clients} clients — is that normal for this ${devType}?`)
      suggestions.push(`What is the uptime and firmware version of ${entity.label}?`)
      if (devType === 'AP') suggestions.push(`Are there any interference issues on ${entity.label}?`)
      if (devType === 'Switch') suggestions.push(`Which ports are most active on ${entity.label}?`)
    }
  } else if (platform === 'pbs') {
    const pct = metadata.usage_pct
    if (pct > 85) {
      suggestions.push(`Datastore at ${Math.round(pct)}% — what can be pruned?`)
      suggestions.push(`What is the retention policy for ${entity.label}?`)
    } else {
      suggestions.push(`When was the last backup to ${entity.label}?`)
      suggestions.push(`How much space will ${entity.label} need in 3 months?`)
    }
    if (metadata.gc_status) suggestions.push(`Is the GC status "${metadata.gc_status}" normal?`)
  } else if (platform === 'truenas') {
    const pct = metadata.usage_pct
    if (status === 'error' || metadata.status !== 'ONLINE') {
      suggestions.push(`Pool ${entity.label} is ${metadata.status} — what does that mean?`)
      suggestions.push(`How do I recover a degraded ZFS pool?`)
    } else if (pct > 80) {
      suggestions.push(`Pool at ${Math.round(pct)}% — what datasets are largest?`)
      suggestions.push(`What are safe ZFS usage thresholds?`)
    } else {
      suggestions.push(`Summarise the health of pool ${entity.label}`)
      suggestions.push(`What is the vdev layout of ${entity.label}?`)
    }
    if (metadata.scan_state) suggestions.push(`Last scrub: ${metadata.scan_state} — should I run another?`)
  } else if (platform === 'fortigate') {
    if (!metadata.link || status === 'error') {
      suggestions.push(`Interface ${entity.label} is down — what are common causes?`)
      suggestions.push(`How do I diagnose a link-down interface on FortiGate?`)
    } else if (status === 'degraded') {
      suggestions.push(`${entity.label} has errors — how do I troubleshoot interface errors?`)
      suggestions.push(`What do RX/TX errors indicate on a FortiGate interface?`)
    } else {
      const speed = metadata.speed ? `${metadata.speed >= 1000 ? `${metadata.speed/1000}G` : `${metadata.speed}M`}` : ''
      suggestions.push(`What traffic flows through ${entity.label}${speed ? ` (${speed})` : ''}?`)
      suggestions.push(`Is the bandwidth on ${entity.label} within normal range?`)
    }
  } else if (entity.id?.startsWith('cluster:') || entity.id?.startsWith('unifi:') && !entity.id?.includes(':device:')) {
    suggestions.push(`Summarise the overall health of ${entity.label}`)
    suggestions.push(`Are there any issues I should be aware of?`)
  } else {
    if (status === 'error' || status === 'degraded') {
      suggestions.push(`What is causing the ${status} status on ${entity.label}?`)
      suggestions.push(`How do I fix this issue?`)
    } else {
      suggestions.push(`Summarise the health of ${entity.label}`)
      suggestions.push(`Are there any optimisations I should consider?`)
    }
  }

  return suggestions.slice(0, 3)
}

export default function ComparePanel({ compareSet, chats, setChats, bcTargets, setBcTargets, onRemove, onClose }) {
  const [bcInput, setBcInput] = useState('')
  const [bcSending, setBcSending] = useState(false)
  const panelWidth = compareSet.length === 1 ? 360 : 580
  const gridCols = compareSet.length > 1 ? '1fr 1fr' : '1fr'
  const gridRows = compareSet.length > 2 ? '1fr 1fr' : '1fr'

  const sendToEntity = (entity, text) => {
    if (!text.trim()) return
    const id = entity.id
    // Add user message + empty AI placeholder in one update
    let aiText = ''
    setChats(prev => ({
      ...prev,
      [id]: [...(prev[id] || []), { role: 'user', text }, { role: 'ai', text: '' }],
    }))
    askAgent(
      { ...entity.metadata, label: entity.label, id: entity.id, platform: entity.platform, section: entity.section },
      text,
      (chunk) => {
        aiText += chunk
        setChats(prev => {
          const msgs = [...(prev[id] || [])]
          if (msgs.length && msgs[msgs.length - 1].role === 'ai') {
            msgs[msgs.length - 1] = { role: 'ai', text: aiText }
          }
          return { ...prev, [id]: msgs }
        })
      },
      () => {},
      (err) => {
        setChats(prev => {
          const msgs = [...(prev[id] || [])]
          if (msgs.length && msgs[msgs.length - 1].role === 'ai') {
            msgs[msgs.length - 1] = { role: 'ai', text: `Error: ${err}` }
          }
          return { ...prev, [id]: msgs }
        })
      }
    )
  }

  const sendBroadcast = () => {
    if (!bcInput.trim() || bcSending) return
    const text = bcInput
    setBcInput('')
    setBcSending(true)
    const targets = compareSet.filter(e => bcTargets[e.id])
    targets.forEach(entity => sendToEntity(entity, text))
    setTimeout(() => setBcSending(false), 500)
  }

  return (
    <div style={{
      width: panelWidth, flexShrink: 0,
      borderLeft: '2px solid var(--border)',
      background: 'var(--bg-0)',
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '8px 12px', borderBottom: '1px solid var(--border)',
        background: 'var(--bg-1)', flexShrink: 0,
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-2)',
                       letterSpacing: '0.08em' }}>
          COMPARE ({compareSet.length})
        </span>
        <button onClick={onClose} style={{
          background: 'none', border: 'none', color: 'var(--text-3)',
          cursor: 'pointer', fontSize: 14, padding: '0 4px',
        }}>✕</button>
      </div>

      {/* Entity grid */}
      <div style={{
        flex: 1, display: 'grid', overflow: 'hidden',
        gridTemplateColumns: gridCols, gridTemplateRows: gridRows,
        gap: 1, background: 'var(--border)',
      }}>
        {compareSet.map((entity, i) => (
          <EntitySlot
            key={entity.id}
            entity={entity}
            slotIndex={i}
            chat={chats[entity.id] || []}
            onSend={(text) => sendToEntity(entity, text)}
            onRemove={() => onRemove(entity.id)}
          />
        ))}
      </div>

      {/* Broadcast row — visible when 2+ entities */}
      {compareSet.length > 1 && (
        <div style={{
          borderTop: '2px solid var(--border)', background: 'var(--bg-0)',
          padding: '8px 10px', flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 8, color: 'var(--text-3)',
                           letterSpacing: '0.06em', flexShrink: 0 }}>SEND TO</span>
            {compareSet.map((e, i) => (
              <button key={e.id}
                onClick={() => setBcTargets(prev => ({ ...prev, [e.id]: !prev[e.id] }))}
                style={{
                  fontSize: 8, padding: '2px 6px', borderRadius: 2,
                  fontFamily: 'var(--font-mono)', cursor: 'pointer',
                  border: `1px solid ${SLOT_COLORS[i]}`,
                  background: bcTargets[e.id] ? `${SLOT_COLORS[i]}22` : 'transparent',
                  color: bcTargets[e.id] ? SLOT_COLORS[i] : 'var(--text-3)',
                  opacity: bcTargets[e.id] ? 1 : 0.5,
                }}
              >{i + 1}</button>
            ))}
            <button
              onClick={() => {
                const allOn = compareSet.every(e => bcTargets[e.id])
                const next = {}
                compareSet.forEach(e => { next[e.id] = !allOn })
                setBcTargets(next)
              }}
              style={{
                fontSize: 8, padding: '2px 6px', borderRadius: 2,
                fontFamily: 'var(--font-mono)', cursor: 'pointer',
                border: '1px solid var(--border)', background: 'transparent',
                color: 'var(--text-3)',
              }}
            >all</button>
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <input
              value={bcInput}
              onChange={e => setBcInput(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') sendBroadcast() }}
              placeholder="Broadcast to selected…"
              style={{
                flex: 1, padding: '5px 8px', fontSize: 11,
                fontFamily: 'var(--font-mono)', color: 'var(--text-1)',
                background: 'var(--bg-2)', border: '1px solid var(--border)',
                borderRadius: 2, outline: 'none',
              }}
            />
            <button onClick={sendBroadcast} disabled={bcSending || !bcInput.trim()}
              style={{
                padding: '5px 12px', fontSize: 10, fontFamily: 'var(--font-mono)',
                color: 'var(--cyan)', background: 'var(--accent-dim)',
                border: '1px solid var(--accent)', borderRadius: 2,
                cursor: bcSending || !bcInput.trim() ? 'not-allowed' : 'pointer',
                opacity: bcSending || !bcInput.trim() ? 0.5 : 1,
              }}>SEND</button>
          </div>
        </div>
      )}
    </div>
  )
}

function EntitySlot({ entity, slotIndex, chat, onSend, onRemove }) {
  const [input, setInput] = useState('')
  const scrollRef = useRef(null)

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight
  }, [chat])

  const send = () => {
    if (!input.trim()) return
    onSend(input)
    setInput('')
  }

  const meta = entity.metadata || {}
  const stats = [
    { label: 'vcpu', value: meta.vcpus ?? meta.vdev_count ?? '—' },
    { label: 'ram', value: meta.maxmem_gb ? `${meta.maxmem_gb}G` : meta.usage_pct ? `${meta.usage_pct}%` : '—' },
    { label: 'cpu%', value: meta.cpu_pct != null ? `${meta.cpu_pct}%` : meta.clients ?? '—' },
    { label: 'status', value: meta.status || meta.state || entity.metadata?.dot || '—' },
  ]

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', background: 'var(--bg-0)',
      borderTop: `2px solid ${SLOT_COLORS[slotIndex]}`, overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px',
        borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        <div style={{
          width: 8, height: 8, borderRadius: '50%', flexShrink: 0,
          background: SLOT_COLORS[slotIndex],
        }} />
        <span style={{
          fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-1)',
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{entity.label}</span>
        <span style={{
          fontSize: 7, padding: '1px 4px', fontFamily: 'var(--font-mono)',
          background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2,
          letterSpacing: 0.5,
        }}>{entity.platform?.toUpperCase()}</span>
        <button onClick={onRemove} style={{
          background: 'none', border: 'none', color: 'var(--text-3)',
          cursor: 'pointer', fontSize: 12, padding: 0,
        }}>✕</button>
      </div>

      {/* Stats row */}
      <div style={{
        display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0,
      }}>
        {stats.map(s => (
          <div key={s.label} style={{
            flex: 1, padding: '4px 0', textAlign: 'center',
            borderRight: '1px solid var(--border)',
          }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-1)', lineHeight: 1 }}>
              {s.value}
            </div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 7, color: 'var(--text-3)', letterSpacing: '0.04em' }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {/* Chat thread */}
      <div ref={scrollRef} style={{
        flex: 1, overflowY: 'auto', padding: '6px 8px',
        display: 'flex', flexDirection: 'column', gap: 4,
      }}>
        {chat.map((msg, i) => (
          <div key={i} style={{
            padding: '4px 8px', fontSize: 10, fontFamily: 'var(--font-mono)',
            lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            background: msg.role === 'user' ? 'var(--bg-2)' : 'var(--accent-dim)',
            borderLeft: `2px solid ${msg.role === 'user' ? 'var(--border)' : 'var(--accent)'}`,
            borderRadius: 2, color: msg.role === 'user' ? 'var(--text-2)' : 'var(--cyan)',
          }}>{msg.text}</div>
        ))}
        {chat.length === 0 && (() => {
          const suggestions = getEntitySuggestions(entity)
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', marginBottom: 2 }}>
                Ask about {entity.label}…
              </span>
              {suggestions.map((s, i) => (
                <button
                  key={i}
                  onClick={() => onSend(s)}
                  style={{
                    fontSize: 9, padding: '3px 7px', textAlign: 'left',
                    border: '1px solid var(--accent-dim)', borderRadius: 2,
                    background: 'transparent', color: 'var(--cyan)',
                    cursor: 'pointer', fontFamily: 'var(--font-mono)', lineHeight: 1.4,
                  }}
                >
                  {s}
                </button>
              ))}
            </div>
          )
        })()}
      </div>

      {/* Input */}
      <div style={{
        display: 'flex', gap: 4, padding: '6px 8px',
        borderTop: '1px solid var(--border)', flexShrink: 0,
      }}>
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') send() }}
          placeholder="Ask…"
          style={{
            flex: 1, padding: '4px 6px', fontSize: 10,
            fontFamily: 'var(--font-mono)', color: 'var(--text-1)',
            background: 'var(--bg-2)', border: '1px solid var(--border)',
            borderRadius: 2, outline: 'none',
          }}
        />
        <button onClick={send} disabled={!input.trim()}
          style={{
            padding: '4px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
            color: 'var(--cyan)', background: 'var(--accent-dim)',
            border: '1px solid var(--accent)', borderRadius: 2,
            cursor: !input.trim() ? 'not-allowed' : 'pointer',
            opacity: !input.trim() ? 0.5 : 1,
          }}>›</button>
      </div>
    </div>
  )
}
