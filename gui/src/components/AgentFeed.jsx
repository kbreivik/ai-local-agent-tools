/**
 * AgentFeed — compact inline activity feed shown in the Commands panel.
 * Appears below the Run Agent button, fills in real-time as the agent runs.
 */
import { useEffect, useRef, useState } from 'react'
import { useAgentOutput } from '../context/AgentOutputContext'
import { submitFeedback } from '../api'
import SubtaskOfferCard from './SubtaskOfferCard'

// ── Tool humanization ─────────────────────────────────────────────────────────

const TOOL_HUMAN = {
  get_host_network:            'Checked host network',
  service_list:                'Listed services',
  swarm_status:                'Checked swarm status',
  kafka_broker_status:         'Checked Kafka brokers',
  kafka_topic_health:          'Checked Kafka topics',
  kafka_consumer_lag:          'Checked consumer lag',
  elastic_cluster_health:      'Checked Elasticsearch',
  elastic_index_stats:         'Checked index stats',
  elastic_error_logs:          'Searched error logs',
  elastic_search_logs:         'Searched logs',
  elastic_log_pattern:         'Analysed log patterns',
  elastic_kafka_logs:          'Checked Kafka logs',
  elastic_correlate_operation: 'Correlated events',
  service_current_version:     'Checked service version',
  service_version_history:     'Looked up version history',
  service_resolve_image:       'Resolved image tag',
  service_health:              'Checked service health',
  pre_upgrade_check:           'Ran pre-upgrade checks',
  pre_kafka_check:             'Ran Kafka pre-flight',
  post_upgrade_verify:         '🔍 Verifying upgrade',
  plan_action:                 '📋 Preparing plan…',
  clarifying_question:         '❓ Asking for clarification',
  escalate:                    'Escalating',
  checkpoint_save:             '💾 Saved checkpoint',
  checkpoint_restore:          '🔄 Restoring checkpoint',
  service_upgrade:             '⚙ Upgrading service…',
  service_rollback:            '↩ Rolling back service…',
  node_drain:                  '🔧 Draining node…',
  kafka_rolling_restart_safe:  '🔄 Restarting Kafka…',
}

function humanizeTool(name) {
  if (!name) return 'Tool'
  if (name in TOOL_HUMAN) return TOOL_HUMAN[name]
  return name.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase())
}

// ── Agent type accent color ───────────────────────────────────────────────────

const AGENT_COLOR = {
  status:   '#3b82f6',
  action:   '#f97316',
  research: '#a855f7',
}

// ── Simple markdown renderer ──────────────────────────────────────────────────

function InlineText({ text }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)/g)
  return (
    <>
      {parts.map((chunk, idx) => {
        if (chunk.startsWith('**') && chunk.endsWith('**'))
          return <strong key={idx}>{chunk.slice(2, -2)}</strong>
        if (chunk.startsWith('`') && chunk.endsWith('`'))
          return (
            <code key={idx} style={{
              fontFamily: 'monospace', background: '#1e2d3d',
              padding: '1px 4px', borderRadius: 3, fontSize: '0.9em',
            }}>
              {chunk.slice(1, -1)}
            </code>
          )
        if (chunk.startsWith('*') && chunk.endsWith('*'))
          return <em key={idx}>{chunk.slice(1, -1)}</em>
        return chunk
      })}
    </>
  )
}

function MarkdownContent({ content }) {
  if (!content) return null
  const lines = content.split('\n')
  const elements = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) { i++; continue }

    // Bullet list
    if (/^\s*[-*+•]\s/.test(line)) {
      const bullets = []
      while (i < lines.length && /^\s*[-*+•]\s/.test(lines[i])) {
        bullets.push(lines[i].replace(/^\s*[-*+•]\s/, ''))
        i++
      }
      elements.push(
        <ul key={`ul${i}`} style={{ margin: '3px 0', paddingLeft: 14, listStyleType: 'disc' }}>
          {bullets.map((b, j) => (
            <li key={j} style={{ marginBottom: 1 }}><InlineText text={b} /></li>
          ))}
        </ul>
      )
      continue
    }

    // Numbered list
    if (/^\s*\d+[.)]\s/.test(line)) {
      const items = []
      while (i < lines.length && /^\s*\d+[.)]\s/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ''))
        i++
      }
      elements.push(
        <ol key={`ol${i}`} style={{ margin: '3px 0', paddingLeft: 14 }}>
          {items.map((item, j) => (
            <li key={j} style={{ marginBottom: 1 }}><InlineText text={item} /></li>
          ))}
        </ol>
      )
      continue
    }

    // Markdown header → render as bold text (no visual headers per style rules)
    if (/^#{1,6}\s/.test(line)) {
      const text = line.replace(/^#{1,6}\s+/, '')
      elements.push(
        <p key={`h${i}`} style={{ margin: '3px 0', fontWeight: 600 }}>
          <InlineText text={text} />
        </p>
      )
      i++
      continue
    }

    // Regular line
    elements.push(
      <p key={`p${i}`} style={{ margin: '2px 0' }}>
        <InlineText text={line} />
      </p>
    )
    i++
  }

  return <>{elements}</>
}

// ── Feed line renderers ───────────────────────────────────────────────────────

function ToolLine({ item }) {
  const isErr      = item.status === 'error' || item.status === 'failed'
  const isDegraded = item.status === 'degraded'
  const isEscalated = item.status === 'escalated' || item.toolName === 'escalate'
  const human = humanizeTool(item.toolName)

  let icon, suffix, color
  if (isErr) {
    icon = '⚠'; suffix = ' failed'; color = '#d97706'
  } else if (isDegraded) {
    icon = '⚠'; suffix = ' — degraded'; color = '#ca8a04'
  } else if (isEscalated) {
    icon = '⚠'; suffix = ' — human review required'; color = '#f59e0b'
  } else {
    icon = '✓'; suffix = ''; color = '#6b7280'
  }

  return (
    <div style={{
      fontSize: 11, lineHeight: 1.6, color,
      display: 'flex', alignItems: 'baseline', gap: 5,
    }}>
      <span style={{ flexShrink: 0, fontSize: 10 }}>{icon}</span>
      <span>{human}{suffix}</span>
    </div>
  )
}

function ThoughtBox({ content, agentColor }) {
  return (
    <div style={{
      borderLeft: `2px solid ${agentColor || '#6b7280'}`,
      padding: '8px 10px',
      marginTop: 6,
      fontSize: 12,
      lineHeight: 1.6,
      color: '#e2e8f0',
      background: 'rgba(255,255,255,0.04)',
      borderRadius: '0 4px 4px 0',
    }}>
      <MarkdownContent content={content} />
    </div>
  )
}

function DoneFooter({ steps, elapsed, sessionId, onFullLog }) {
  const [given, setGiven] = useState(null)  // null | 'thumbs_up' | 'thumbs_down'

  const rate = async (rating) => {
    if (given || !sessionId) return
    setGiven(rating)
    try { await submitFeedback(sessionId, rating) } catch { /* ignore */ }
  }

  return (
    <div style={{
      marginTop: 6,
      paddingTop: 6,
      borderTop: '1px solid #1e293b',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      fontSize: 10,
      color: '#64748b',
    }}>
      <span>{steps} steps · {elapsed}s</span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {given ? (
          <span style={{ color: '#475569', fontSize: 10 }}>
            {given === 'thumbs_up' ? '👍 Saved' : '👎 Saved'}
          </span>
        ) : sessionId ? (
          <>
            <button
              onClick={() => rate('thumbs_up')}
              title="Good response"
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, padding: 0, lineHeight: 1 }}
            >👍</button>
            <button
              onClick={() => rate('thumbs_down')}
              title="Poor response"
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13, padding: 0, lineHeight: 1 }}
            >👎</button>
          </>
        ) : null}
        <button
          onClick={() => {
            if (sessionId) {
              window.dispatchEvent(new CustomEvent('open-session-output', { detail: { session_id: sessionId } }))
              window.dispatchEvent(new CustomEvent('navigate-to-logs'))
            } else {
              onFullLog?.()
            }
          }}
          style={{
            fontSize: 10, color: '#3b82f6', background: 'none',
            border: 'none', cursor: 'pointer', padding: 0,
            textDecoration: 'underline',
          }}
        >
          Full log →
        </button>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function AgentFeed() {
  const { feedLines, agentType, lastAgentType } = useAgentOutput()
  const bottomRef   = useRef(null)
  const [visible,   setVisible] = useState(false)
  const [dismissedOffers, setDismissedOffers] = useState(new Set())

  const accentColor = AGENT_COLOR[agentType || lastAgentType] || '#6b7280'

  // Slide-in animation on first appearance
  useEffect(() => {
    if (feedLines.length > 0 && !visible) setVisible(true)
  }, [feedLines.length])

  // Auto-scroll to bottom as new items arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [feedLines.length])

  if (feedLines.length === 0) return null

  const navigateToOutput = () =>
    window.dispatchEvent(new CustomEvent('navigate-to-output'))

  return (
    <div
      style={{
        maxHeight: 420,
        overflowY: 'auto',
        padding: '10px 12px',
        background: '#0f172a',
        borderTop: '1px solid #1e293b',
        fontFamily: "'Courier New', monospace",
        opacity:    visible ? 1 : 0,
        transform:  visible ? 'translateY(0)' : 'translateY(-4px)',
        transition: 'opacity 0.2s ease, transform 0.2s ease',
      }}
    >
      {feedLines.map((item, i) => {
        if (item.type === 'start') {
          return (
            <div key={i} style={{ fontSize: 11, color: '#64748b', fontStyle: 'italic', lineHeight: 1.6 }}>
              🔍 Looking into that now…
            </div>
          )
        }

        if (item.type === 'tool') {
          return <ToolLine key={i} item={item} />
        }

        if (item.type === 'thought') {
          const redundantPattern = /\s+I (have completed|will now|have finished|will now provide|have now completed)[^.!]*[.!]/gi
          const cleaned = item.content.replace(redundantPattern, '').trim()
          return <ThoughtBox key={i} content={cleaned} agentColor={accentColor} />
        }

        if (item.type === 'done') {
          return (
            <DoneFooter
              key={i}
              steps={item.steps}
              elapsed={item.elapsed}
              sessionId={item.sessionId}
              onFullLog={navigateToOutput}
            />
          )
        }

        if (item.type === 'error') {
          return (
            <div key={i} style={{ fontSize: 11, color: '#ef4444', lineHeight: 1.6, marginTop: 4 }}>
              ✗ Something went wrong
            </div>
          )
        }

        if (item.type === 'subtask_offer') {
          if (dismissedOffers.has(i)) return null
          return (
            <SubtaskOfferCard
              key={i}
              proposals={item.proposals}
              onDismiss={() => setDismissedOffers(prev => new Set([...prev, i]))}
            />
          )
        }

        if (item.type === 'cancelled') {
          return (
            <div key={i} style={{ fontSize: 11, color: '#64748b', lineHeight: 1.6, marginTop: 4 }}>
              ◼ Stopped.
            </div>
          )
        }

        return null
      })}
      <div ref={bottomRef} />
    </div>
  )
}
