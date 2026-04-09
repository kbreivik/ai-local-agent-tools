/**
 * ComparePanel — right-side panel showing up to 4 selected entities
 * with per-entity chat threads and a broadcast row.
 */
import { useState, useRef, useEffect } from 'react'
import { askAgent } from '../api'

export const SLOT_COLORS = ['#00aa44','#00c8ee','#cc8800','#7c6af7']

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
        {chat.length === 0 && (
          <span style={{ fontSize: 9, color: 'var(--text-3)', fontFamily: 'var(--font-mono)' }}>
            Ask about {entity.label}…
          </span>
        )}
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
