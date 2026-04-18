import React, { useEffect, useMemo, useState } from 'react';

/**
 * PreflightPanel — v2.35.1
 *
 * Renders the result of the agent preflight resolver (regex → keyword DB → LLM).
 * Appears above the command feed whenever an operation is `awaiting_clarification`
 * OR when preflightPanelMode=always_visible and a preflight has been emitted.
 *
 * Props:
 *   preflight:  PreflightResult (as serialised by the backend)
 *   sessionId:  current operation session id
 *   onPick:     (candidateEntityId) => void
 *   onRefine:   (refinedTask) => void
 *   onCancel:   () => void
 *   mode:       'on_ambiguity' | 'always_visible' | 'off'
 *   timeoutSec: auto-cancel countdown seconds (default 300)
 */
export default function PreflightPanel({
  preflight,
  sessionId,
  onPick,
  onRefine,
  onCancel,
  mode = 'always_visible',
  timeoutSec = 300,
}) {
  const [expanded, setExpanded] = useState(false);
  const [refineDraft, setRefineDraft] = useState('');
  const [remaining, setRemaining] = useState(timeoutSec);

  const ambiguous = !!preflight?.ambiguous;

  useEffect(() => {
    if (!ambiguous) return;
    setExpanded(true);
    setRemaining(timeoutSec);
    const started = Date.now();
    const tick = setInterval(() => {
      const elapsed = Math.floor((Date.now() - started) / 1000);
      const left = Math.max(0, timeoutSec - elapsed);
      setRemaining(left);
      if (left <= 0) clearInterval(tick);
    }, 1000);
    return () => clearInterval(tick);
  }, [ambiguous, timeoutSec, sessionId]);

  const candidates = useMemo(() => {
    if (!preflight?.candidates) return [];
    return preflight.candidates;
  }, [preflight]);

  if (!preflight) return null;
  if (mode === 'off') return null;
  if (mode === 'on_ambiguity' && !ambiguous) return null;

  const classifier = preflight.agent_type || '?';
  const tierUsed = preflight.tier_used || '?';
  const factCount = (preflight.preflight_facts || []).length;

  const timeHintsTrace = (preflight.trace || []).filter(t => t.startsWith('time-hint'));
  const keywordTrace = (preflight.trace || []).filter(t => t.startsWith('keyword'));
  const extracted = candidates
    .map(b => b?.candidate?.entity_id)
    .filter(Boolean);

  const countdown = (() => {
    const mm = String(Math.floor(remaining / 60)).padStart(1, '0');
    const ss = String(remaining % 60).padStart(2, '0');
    return `${mm}:${ss}`;
  })();

  const collapsed = !expanded && !ambiguous;

  return (
    <div
      className="preflight-panel"
      style={{
        border: '1px solid var(--accent, #a01828)',
        borderRadius: 'var(--radius-card, 2px)',
        padding: '10px 12px',
        margin: '8px 0',
        background: 'var(--bg-1, #09090f)',
        fontFamily: 'var(--font-mono, monospace)',
        fontSize: 13,
      }}
    >
      <div
        style={{ display: 'flex', justifyContent: 'space-between',
                 alignItems: 'center', cursor: 'pointer' }}
        onClick={() => setExpanded(x => !x)}
      >
        <div style={{ color: 'var(--accent, #a01828)', letterSpacing: 1 }}>
          ▸ PREFLIGHT {ambiguous && '⚠ AMBIGUOUS'}
        </div>
        <div style={{ color: 'var(--cyan, #00c8ee)', fontSize: 11 }}>
          {collapsed
            ? `${tierUsed} · ${candidates.length} candidate(s) · ${factCount} fact(s)`
            : (ambiguous ? `auto-cancel in ${countdown}` : 'click to collapse')}
        </div>
      </div>

      {!collapsed && (
        <div style={{ marginTop: 10 }}>
          <div>Classifier:    {classifier}</div>
          <div>
            Extracted:     [{extracted.map(e => `"${e}"`).join(', ')}]
            {ambiguous && <span style={{ color: 'var(--amber, #cc8800)' }}>  ← ambiguous</span>}
          </div>
          {timeHintsTrace.length > 0 && (
            <div>Time window:   {timeHintsTrace.join(' · ')}</div>
          )}
          {keywordTrace.length > 0 && (
            <div>Keywords:      {keywordTrace.join(' · ')}</div>
          )}
          <div>Facts to inject: {factCount}</div>

          {ambiguous && candidates.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <div style={{ color: 'var(--accent, #a01828)' }}>
                Candidate matches ({candidates.length}):
              </div>
              <ol style={{ margin: '4px 0 10px 20px', paddingLeft: 0 }}>
                {candidates.map((block, idx) => {
                  const cand = block?.candidate || {};
                  const matches = block?.matches || [];
                  const label = cand.entity_id || '(unnamed)';
                  const evidence = cand.evidence || '';
                  const matchLabel = matches[0]?.display_name || label;
                  return (
                    <li key={`${label}-${idx}`} style={{ marginBottom: 2 }}>
                      <button
                        type="button"
                        onClick={() => onPick && onPick(matchLabel)}
                        style={{
                          background: 'transparent', border: 'none',
                          color: 'var(--cyan, #00c8ee)', cursor: 'pointer',
                          fontFamily: 'inherit', padding: 0,
                          textDecoration: 'underline',
                        }}
                        title={evidence}
                      >
                        {matchLabel}
                      </button>
                      {evidence && (
                        <span style={{ color: 'var(--amber, #cc8800)', marginLeft: 8 }}>
                          ({evidence})
                        </span>
                      )}
                    </li>
                  );
                })}
              </ol>
            </div>
          )}

          {ambiguous && (
            <div style={{ marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <input
                type="text"
                placeholder="Or rewrite the task…"
                value={refineDraft}
                onChange={(e) => setRefineDraft(e.target.value)}
                style={{
                  flex: '1 1 200px', background: 'var(--bg-2, #0d0f1a)',
                  border: '1px solid var(--accent, #a01828)',
                  color: 'var(--cyan, #00c8ee)', padding: '4px 6px',
                  fontFamily: 'inherit',
                }}
              />
              <button
                type="button"
                onClick={() => refineDraft.trim() && onRefine && onRefine(refineDraft.trim())}
                disabled={!refineDraft.trim()}
              >
                Edit task
              </button>
              <button type="button" onClick={() => onCancel && onCancel()}>
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
