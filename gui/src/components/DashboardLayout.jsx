/**
 * DashboardLayout — renders a configurable tile grid from layout.rows.
 * Supports drag-reorder, drag-to-split (5-zone: left/top/center/bottom/right),
 * vertical column groups, split/unsplit, collapse, resize, auto-fit heightMode,
 * and auto-scroll during drag.
 *
 * Props:
 *   layout      — { rows, collapsed, prefs }
 *   onRowsChange(rows)       — called when rows are reordered/split/unsplit
 *   onCollapsedChange(tile)  — called to toggle collapse on a tile
 *   children    — map of tile-name → React node (section content)
 */
import React, { useState, useRef, useCallback, useEffect, useLayoutEffect } from 'react'

class SectionErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { hasError: false }
  }
  static getDerivedStateFromError() {
    return { hasError: true }
  }
  componentDidCatch(error) {
    console.error(`[DEATHSTAR] Section '${this.props.sectionName}' crashed:`, error)
  }
  render() {
    if (!this.state.hasError) return this.props.children
    return (
      <div style={{
        padding: '12px 14px', background: 'var(--bg-2)',
        border: '1px solid var(--border)', borderLeft: '3px solid var(--red)',
        borderRadius: 2, fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--red)',
      }}>
        ✕ {this.props.sectionName || 'Section'} unavailable — check browser console
      </div>
    )
  }
}

const TILE_META = {
  PLATFORM:   { icon: '⬡', badge: 'INTERNAL' },
  COMPUTE:    { icon: '◈', badge: 'HYPERVISORS' },
  CONTAINERS: { icon: '⊟', badge: 'DOCKER' },
  NETWORK:    { icon: '◉', badge: 'INFRA' },
  STORAGE:    { icon: '⊠', badge: 'DATA' },
  SECURITY:   { icon: '⊛', badge: 'SOC' },
  VM_HOSTS:   { icon: '⬢', badge: 'NODES' },
  WINDOWS:    { icon: '⊞', badge: 'WINRM' },
}

// Human-readable display names for tile headers (key → label)
const TILE_DISPLAY_NAMES = {
  PLATFORM:   'Platform',
  COMPUTE:    'Compute',
  CONTAINERS: 'Containers',
  NETWORK:    'Network',
  STORAGE:    'Storage',
  SECURITY:   'Security',
  VM_HOSTS:   'VM Hosts',
  WINDOWS:    'Windows',
}

const ACTION_BTN = {
  fontSize: 9, cursor: 'pointer', background: 'none', border: 'none',
  padding: '5px 7px', margin: '-5px -3px', minWidth: 26, minHeight: 26,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}

// ── Helpers for tiles that can be strings or col-group objects ────────────

function tileKey(item) {
  if (typeof item === 'string') return item
  if (item?.col) return `col:${item.col.join('+')}`
  return String(item)
}

function rowArrangementKey(rows) {
  return JSON.stringify(rows.map(r =>
    r.tiles.map(t => typeof t === 'string' ? t : `col(${t.col?.join(',')})`).join('|')
  ))
}

// Remove a tile from wherever it is (plain or inside col group).
// Cleans up empty col groups and empty rows automatically.
function removeTileFromRows(rows, tileName) {
  return rows.map(row => ({
    ...row,
    tiles: row.tiles
      .map(item => {
        if (typeof item === 'string') return item === tileName ? null : item
        if (typeof item === 'object' && item.col) {
          const newCol = item.col.filter(t => t !== tileName)
          if (newCol.length === 0) return null
          if (newCol.length === 1) return newCol[0]
          const newFlex = item.flex
            ? item.flex.filter((_, i) => item.col[i] !== tileName)
            : undefined
          return { ...item, col: newCol, ...(newFlex ? { flex: newFlex } : {}) }
        }
        return item
      })
      .filter(Boolean),
  })).filter(row => row.tiles.length > 0)
}

// Find a tile (string) in rows — returns { rowIdx, itemIdx, colIdx, inCol }
function findTileInRows(rows, tileName) {
  for (let ri = 0; ri < rows.length; ri++) {
    for (let ii = 0; ii < rows[ri].tiles.length; ii++) {
      const item = rows[ri].tiles[ii]
      if (typeof item === 'string' && item === tileName) {
        return { rowIdx: ri, itemIdx: ii, colIdx: -1, inCol: false }
      }
      if (typeof item === 'object' && item.col) {
        const ci = item.col.indexOf(tileName)
        if (ci !== -1) return { rowIdx: ri, itemIdx: ii, colIdx: ci, inCol: true }
      }
    }
  }
  return null
}

// ── Resize handles ───────────────────────────────────────────────────────

function ResizeHandle({ onResize, rowFlex }) {
  const handleRef = useRef(null)
  const onMouseDown = useCallback((e) => {
    e.preventDefault()
    const startX = e.clientX
    const rowEl = handleRef.current?.closest('.ds-row')
    const rowWidth = rowEl ? rowEl.getBoundingClientRect().width : 1000
    const totalFlex = (rowFlex || []).reduce((a, b) => a + b, 0) || 1
    const pixelPerFlex = rowWidth / totalFlex
    const onMove = (me) => onResize(me.clientX - startX, pixelPerFlex)
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [onResize, rowFlex])
  return <div ref={handleRef} className="ds-resize-handle" onMouseDown={onMouseDown} />
}

function VerticalResizeHandle({ onResize, colFlex }) {
  const ref = useRef(null)
  const onMouseDown = useCallback((e) => {
    e.preventDefault()
    const startY = e.clientY
    const colEl = ref.current?.closest('.ds-col-group')
    const colH = colEl ? colEl.getBoundingClientRect().height : 600
    const total = (colFlex || []).reduce((a, b) => a + b, 0) || 1
    const pxPerFlex = colH / total
    const onMove = (me) => onResize(me.clientY - startY, pxPerFlex)
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [onResize, colFlex])
  return <div ref={ref} className="ds-col-resize-handle" onMouseDown={onMouseDown} />
}

// ── Tile component ───────────────────────────────────────────────────────

function Tile({ name, flex, collapsed, heightMode, dragDropSide,
                onDragStart, onDragOver, onDrop, onDragEnd,
                onCollapse, onSplit, onUnsplit, onHeightModeToggle, canUnsplit,
                splitCandidates, children, draggingOver }) {
  const meta = TILE_META[name] || { icon: '▪', badge: '' }
  const [splitMenuOpen, setSplitMenuOpen] = useState(false)
  const classes = ['ds-tile', collapsed ? 'collapsed' : ''].filter(Boolean).join(' ')

  const detectSide = (e) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const relX = (e.clientX - rect.left) / rect.width
    const relY = (e.clientY - rect.top) / rect.height
    if (relX < 0.25) return 'left'
    if (relX > 0.75) return 'right'
    if (relY < 0.25) return 'top'
    if (relY > 0.75) return 'bottom'
    return 'center'
  }

  return (
    <div
      className={classes}
      style={{ flex: flex ?? 1, position: 'relative' }}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', name)
        e.dataTransfer.effectAllowed = 'move'
        onDragStart(name)
      }}
      onDragOver={(e) => { e.preventDefault(); onDragOver?.(name, detectSide(e)) }}
      onDrop={(e) => { e.preventDefault(); onDrop?.(name, detectSide(e)) }}
      onDragEnd={() => onDragEnd?.()}
    >
      {/* 5-zone drop overlay */}
      {draggingOver && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 10, pointerEvents: 'none',
                      display: 'grid', gridTemplate: '25% 50% 25% / 25% 50% 25%' }}>
          <div style={{ gridColumn: '1/4', gridRow: '1',
            background: dragDropSide === 'top' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderTop: dragDropSide === 'top' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.08s' }} />
          <div style={{ gridColumn: '1', gridRow: '1/4',
            background: dragDropSide === 'left' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderLeft: dragDropSide === 'left' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.08s' }} />
          <div style={{ gridColumn: '2', gridRow: '2',
            background: dragDropSide === 'center' ? 'rgba(0,200,238,0.07)' : 'transparent',
            transition: 'all 0.08s' }} />
          <div style={{ gridColumn: '3', gridRow: '1/4',
            background: dragDropSide === 'right' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderRight: dragDropSide === 'right' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.08s' }} />
          <div style={{ gridColumn: '1/4', gridRow: '3',
            background: dragDropSide === 'bottom' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderBottom: dragDropSide === 'bottom' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.08s' }} />
        </div>
      )}
      <div className="ds-tile-hdr">
        <span style={{ cursor: 'grab', color: 'var(--text-3)', fontSize: 11 }}>⠿</span>
        <span style={{ fontSize: 11 }}>{meta.icon}</span>
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          {TILE_DISPLAY_NAMES[name] || name}
        </span>
        {meta.badge && (
          <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2, letterSpacing: 1 }}>
            {meta.badge}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {!canUnsplit && splitCandidates?.length > 0 && (
          <div style={{ position: 'relative', display: 'inline-flex' }}>
            <button onClick={(e) => { e.stopPropagation(); setSplitMenuOpen(o => !o) }}
              style={{ ...ACTION_BTN, color: 'var(--text-3)' }} title="Split — add tile to this row">⊞</button>
            {splitMenuOpen && (
              <div style={{ position: 'absolute', top: '100%', right: 0, zIndex: 50,
                background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 2, minWidth: 120, marginTop: 2 }}>
                {splitCandidates.map(c => (
                  <button key={c} onClick={(e) => { e.stopPropagation(); onSplit(c); setSplitMenuOpen(false) }}
                    style={{ display: 'block', width: '100%', textAlign: 'left', padding: '4px 8px', fontSize: 9,
                      fontFamily: 'var(--font-mono)', background: 'none', border: 'none', color: 'var(--text-2)', cursor: 'pointer' }}
                    onMouseOver={e => e.currentTarget.style.background = 'var(--bg-3)'}
                    onMouseOut={e => e.currentTarget.style.background = 'none'}
                  >{c}</button>
                ))}
              </div>
            )}
          </div>
        )}
        {canUnsplit && (
          <button onClick={(e) => { e.stopPropagation(); onUnsplit() }}
            style={{ ...ACTION_BTN, color: 'var(--text-3)' }} title="Unsplit — move to own row">⊟</button>
        )}
        {canUnsplit && (
          <button onClick={(e) => { e.stopPropagation(); onHeightModeToggle() }}
            style={{ ...ACTION_BTN, color: heightMode === 'constrained' ? 'var(--cyan)' : 'var(--text-3)' }}
            title={heightMode === 'constrained' ? 'Height: capped — click for auto' : 'Height: auto — click to cap'}
          >{heightMode === 'constrained' ? '⊡' : '⊞'}</button>
        )}
        <button onClick={(e) => { e.stopPropagation(); onCollapse() }}
          style={{ ...ACTION_BTN, color: 'var(--text-3)' }}
          title={collapsed ? 'Expand' : 'Collapse'}>{collapsed ? '▶' : '▼'}</button>
      </div>
      {!collapsed && <div className="ds-tile-body">{children}</div>}
    </div>
  )
}

// ── Main layout component ────────────────────────────────────────────────

export default function DashboardLayout({ layout, onRowsChange, onCollapsedChange, children }) {
  const [dragSource, setDragSource] = useState(null)
  const [dragOverTarget, setDragOverTarget] = useState(null)
  const [dragDropSide, setDragDropSide] = useState('center')
  const dragSourceRef = useRef(null)
  const dragOverTargetRef = useRef(null)
  const dragDropSideRef = useRef('center')

  const startDrag = useCallback((name) => {
    dragSourceRef.current = name
    setDragSource(name)
  }, [])

  const clearDrag = useCallback(() => {
    dragSourceRef.current = null
    setDragSource(null)
    setDragOverTarget(null)
    setDragDropSide('center')
    dragOverTargetRef.current = null
    dragDropSideRef.current = 'center'
  }, [])

  // ── Auto-scroll during drag ────────────────────────────────────────────
  const scrollIntervalRef = useRef(null)
  useEffect(() => {
    const CONTAINER_SEL = '.flex-1.overflow-auto.min-h-0'
    const SCROLL_ZONE = 200
    const SCROLL_SPEED = 30

    const onDragOver = (e) => {
      const container = document.querySelector(CONTAINER_SEL)
      if (!container) return
      const rect = container.getBoundingClientRect()
      const relY = e.clientY - rect.top
      const fromBottom = rect.height - relY
      clearInterval(scrollIntervalRef.current)
      if (relY < SCROLL_ZONE && relY >= 0) {
        const t = 1 - relY / SCROLL_ZONE
        const speed = Math.round(SCROLL_SPEED * t * t * 3)
        scrollIntervalRef.current = setInterval(() => container.scrollBy({ top: -speed, behavior: 'instant' }), 16)
      } else if (fromBottom < SCROLL_ZONE && fromBottom >= 0) {
        const t = 1 - fromBottom / SCROLL_ZONE
        const speed = Math.round(SCROLL_SPEED * t * t * 3)
        scrollIntervalRef.current = setInterval(() => container.scrollBy({ top: speed, behavior: 'instant' }), 16)
      }
    }
    const stopScroll = () => clearInterval(scrollIntervalRef.current)
    document.addEventListener('dragover', onDragOver)
    document.addEventListener('dragend', stopScroll)
    document.addEventListener('drop', stopScroll)
    return () => {
      document.removeEventListener('dragover', onDragOver)
      document.removeEventListener('dragend', stopScroll)
      document.removeEventListener('drop', stopScroll)
      clearInterval(scrollIntervalRef.current)
    }
  }, [])

  // ── Auto-fit height detection ──────────────────────────────────────────
  const tileArrangementKey = rowArrangementKey(layout.rows)
  const autoFitRunningRef = useRef(false)
  useLayoutEffect(() => {
    if (autoFitRunningRef.current) return
    autoFitRunningRef.current = true
    const dsRows = document.querySelectorAll('.ds-row')
    let changed = false
    const newRows = layout.rows.map((row, ri) => {
      if (row.heightMode === 'constrained') return row
      // Count actual tile slots (col groups count as 1)
      if (row.tiles.length < 2) {
        if ((row.heightMode || 'auto') === 'auto') return row
        changed = true
        return { ...row, heightMode: 'auto' }
      }
      const rowEl = dsRows[ri]
      if (!rowEl) return row
      const bodies = Array.from(rowEl.querySelectorAll(':scope > span > .ds-tile .ds-tile-body, :scope > .ds-tile .ds-tile-body, :scope > span > .ds-col-group .ds-tile-body'))
      const heights = bodies.map(b => b.scrollHeight).filter(h => h > 0)
      if (heights.length < 2) return row
      const maxH = Math.max(...heights)
      const minH = Math.min(...heights)
      const ratio = minH > 0 ? maxH / minH : 1
      const computed = ratio > 1.5 ? 'auto' : 'stretch'
      if ((row.heightMode || 'auto') === computed) return row
      changed = true
      return { ...row, heightMode: computed }
    })
    if (changed) onRowsChange(newRows)
    setTimeout(() => { autoFitRunningRef.current = false }, 100)
  }, [tileArrangementKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Split candidates ───────────────────────────────────────────────────
  const getSplitCandidates = useCallback((rowIdx) => {
    const currentRow = layout.rows[rowIdx]
    const currentTileNames = currentRow.tiles.flatMap(t =>
      typeof t === 'string' ? [t] : t.col || []
    )
    const candidates = []
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) continue
      const row = layout.rows[ri]
      if (row.tiles.length === 1 && typeof row.tiles[0] === 'string') {
        if (!currentTileNames.includes(row.tiles[0])) {
          candidates.push(row.tiles[0])
        }
      }
    }
    return candidates.sort()
  }, [layout.rows])

  // ── Drag handlers ──────────────────────────────────────────────────────
  const handleDragOver = useCallback((tileName, side) => {
    if (dragOverTargetRef.current !== tileName) {
      dragOverTargetRef.current = tileName
      setDragOverTarget(tileName)
    }
    if (dragDropSideRef.current !== side) {
      dragDropSideRef.current = side
      setDragDropSide(side)
    }
  }, [])

  const handleDrop = useCallback((targetTile, side) => {
    const src = dragSourceRef.current
    if (!src || src === targetTile) { clearDrag(); return }

    // Deep-copy rows preserving col-group objects
    const newRows = layout.rows.map(row => ({
      ...row,
      tiles: row.tiles.map(t => typeof t === 'object' && t.col ? { ...t, col: [...t.col], flex: t.flex ? [...t.flex] : undefined } : t),
      ...(row.flex ? { flex: [...row.flex] } : {}),
    }))

    if (side === 'left' || side === 'right') {
      // ── Horizontal auto-split ──────────────────────────────────────
      const cleaned = removeTileFromRows(newRows, src)
      const found = findTileInRows(cleaned, targetTile)
      if (!found) { onRowsChange(cleaned); clearDrag(); return }

      const { rowIdx } = found
      let tgtItemIdx = -1
      for (let ii = 0; ii < cleaned[rowIdx].tiles.length; ii++) {
        const item = cleaned[rowIdx].tiles[ii]
        if (typeof item === 'string' && item === targetTile) { tgtItemIdx = ii; break }
        if (typeof item === 'object' && item.col?.includes(targetTile)) { tgtItemIdx = ii; break }
      }
      if (tgtItemIdx === -1) { onRowsChange(cleaned); clearDrag(); return }

      const insertAt = side === 'left' ? tgtItemIdx : tgtItemIdx + 1
      cleaned[rowIdx].tiles.splice(insertAt, 0, src)
      cleaned[rowIdx].flex = Array(cleaned[rowIdx].tiles.length).fill(1)
      delete cleaned[rowIdx].heightMode
      onRowsChange(cleaned)

    } else if (side === 'top' || side === 'bottom') {
      // ── Vertical split: create or extend col group ─────────────────
      const cleaned = removeTileFromRows(newRows, src)
      const found = findTileInRows(cleaned, targetTile)
      if (!found) { onRowsChange(cleaned); clearDrag(); return }

      const { rowIdx, itemIdx, colIdx, inCol } = found

      if (inCol) {
        const col = cleaned[rowIdx].tiles[itemIdx]
        const insertAt = side === 'top' ? colIdx : colIdx + 1
        const newCol = [...col.col]
        newCol.splice(insertAt, 0, src)
        cleaned[rowIdx].tiles[itemIdx] = { ...col, col: newCol, flex: Array(newCol.length).fill(1) }
      } else {
        const colGroup = side === 'top'
          ? { col: [src, targetTile], flex: [1, 1] }
          : { col: [targetTile, src], flex: [1, 1] }
        cleaned[rowIdx].tiles[itemIdx] = colGroup
      }
      onRowsChange(cleaned)

    } else {
      // ── Center: row reorder ────────────────────────────────────────
      let srcRowIdx = -1, tgtRowIdx = -1
      for (let ri = 0; ri < newRows.length; ri++) {
        for (const item of newRows[ri].tiles) {
          if (typeof item === 'string') {
            if (item === src) srcRowIdx = ri
            if (item === targetTile) tgtRowIdx = ri
          } else if (item?.col) {
            if (item.col.includes(src)) srcRowIdx = ri
            if (item.col.includes(targetTile)) tgtRowIdx = ri
          }
        }
      }
      if (srcRowIdx === -1 || tgtRowIdx === -1 || srcRowIdx === tgtRowIdx) {
        if (srcRowIdx === tgtRowIdx && srcRowIdx !== -1) {
          const row = newRows[srcRowIdx]
          const si = row.tiles.findIndex(t => (typeof t === 'string' && t === src) || (t?.col?.includes(src)))
          const ti = row.tiles.findIndex(t => (typeof t === 'string' && t === targetTile) || (t?.col?.includes(targetTile)))
          if (si !== -1 && ti !== -1) {
            ;[row.tiles[si], row.tiles[ti]] = [row.tiles[ti], row.tiles[si]]
            if (row.flex) [row.flex[si], row.flex[ti]] = [row.flex[ti], row.flex[si]]
          }
        }
        onRowsChange(newRows)
      } else {
        const [srcRow] = newRows.splice(srcRowIdx, 1)
        const adjustedTgt = tgtRowIdx > srcRowIdx ? tgtRowIdx - 1 : tgtRowIdx
        newRows.splice(adjustedTgt, 0, srcRow)
        onRowsChange(newRows)
      }
    }

    clearDrag()
  }, [layout.rows, onRowsChange, clearDrag])

  // ── Button-triggered split (dropdown picker) ───────────────────────────
  const handleSplit = useCallback((rowIdx, targetTileName) => {
    const currentRow = layout.rows[rowIdx]
    let pickRowIdx = -1
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) continue
      if (layout.rows[ri].tiles.length === 1 && layout.rows[ri].tiles[0] === targetTileName) {
        pickRowIdx = ri; break
      }
    }
    if (pickRowIdx === -1) return
    const newRows = layout.rows
      .filter((_, ri) => ri !== pickRowIdx)
      .map(row => {
        if (row === currentRow) {
          return { tiles: [...row.tiles, targetTileName], flex: [...(row.flex || row.tiles.map(() => 1)), 2] }
        }
        return { ...row }
      })
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  // ── Unsplit from horizontal row ────────────────────────────────────────
  const handleUnsplit = useCallback((rowIdx, tileIdx) => {
    const row = layout.rows[rowIdx]
    if (row.tiles.length <= 1) return
    const item = row.tiles[tileIdx]
    const tileName = typeof item === 'string' ? item : null
    if (!tileName) return // can't unsplit a col group this way
    const newRows = []
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) {
        const remainingTiles = row.tiles.filter((_, ti) => ti !== tileIdx)
        const remainingFlex = row.flex ? row.flex.filter((_, ti) => ti !== tileIdx) : undefined
        newRows.push({ tiles: remainingTiles, ...(remainingFlex && remainingFlex.length > 1 ? { flex: remainingFlex } : {}) })
        newRows.push({ tiles: [tileName] })
      } else {
        newRows.push({ ...layout.rows[ri] })
      }
    }
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  // ── Unsplit from vertical col group ────────────────────────────────────
  const handleUnsplitFromCol = useCallback((rowIdx, itemIdx, colIdx) => {
    const row = layout.rows[rowIdx]
    const colGroup = row.tiles[itemIdx]
    if (!colGroup?.col || colGroup.col.length <= 1) return
    const tileName = colGroup.col[colIdx]
    const newCol = colGroup.col.filter((_, i) => i !== colIdx)
    const newFlex = (colGroup.flex || colGroup.col.map(() => 1)).filter((_, i) => i !== colIdx)
    const newItem = newCol.length === 1 ? newCol[0] : { ...colGroup, col: newCol, flex: newFlex }
    const newTiles = row.tiles.map((t, i) => i === itemIdx ? newItem : t)
    const newRows = layout.rows.map((r, ri) => ri === rowIdx ? { ...r, tiles: newTiles } : r)
    newRows.splice(rowIdx + 1, 0, { tiles: [tileName] })
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  const handleHeightModeToggle = useCallback((rowIdx) => {
    const newRows = layout.rows.map((r, ri) => {
      if (ri !== rowIdx) return r
      return { ...r, heightMode: (r.heightMode || 'auto') === 'constrained' ? 'auto' : 'constrained' }
    })
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  const handleFlexChange = useCallback((rowIdx, tileIdx, delta, pixelPerFlex) => {
    const row = layout.rows[rowIdx]
    if (row.tiles.length < 2) return
    const flex = row.flex ? [...row.flex] : row.tiles.map(() => 1)
    const flexDelta = delta / (pixelPerFlex || 100)
    flex[tileIdx] = Math.max(0.5, flex[tileIdx] + flexDelta)
    if (tileIdx + 1 < flex.length) flex[tileIdx + 1] = Math.max(0.5, flex[tileIdx + 1] - flexDelta)
    onRowsChange(layout.rows.map((r, ri) => ri === rowIdx ? { ...r, flex } : r))
  }, [layout.rows, onRowsChange])

  const handleColFlexChange = useCallback((rowIdx, itemIdx, tileIdx, delta, pixelPerFlex) => {
    const row = layout.rows[rowIdx]
    const item = row.tiles[itemIdx]
    if (!item?.col || item.col.length < 2) return
    const flex = item.flex ? [...item.flex] : item.col.map(() => 1)
    const flexDelta = delta / (pixelPerFlex || 100)
    flex[tileIdx] = Math.max(0.5, flex[tileIdx] + flexDelta)
    if (tileIdx + 1 < flex.length) flex[tileIdx + 1] = Math.max(0.5, flex[tileIdx + 1] - flexDelta)
    onRowsChange(layout.rows.map((r, ri) =>
      ri !== rowIdx ? r : { ...r, tiles: r.tiles.map((t, ii) => ii !== itemIdx ? t : { ...item, flex }) }
    ))
  }, [layout.rows, onRowsChange])

  // ── Shared tile props builder ──────────────────────────────────────────
  const tileProps = (tileName, ri, row) => ({
    name: tileName,
    collapsed: layout.collapsed?.includes(tileName),
    heightMode: row.heightMode || 'auto',
    onDragStart: startDrag,
    onDragOver: handleDragOver,
    onDrop: handleDrop,
    onDragEnd: clearDrag,
    onCollapse: () => onCollapsedChange(tileName),
    onSplit: (target) => handleSplit(ri, target),
    onHeightModeToggle: () => handleHeightModeToggle(ri),
    splitCandidates: getSplitCandidates(ri),
    draggingOver: dragOverTarget === tileName && dragSource !== tileName,
    dragDropSide: dragOverTarget === tileName && dragSource !== tileName ? dragDropSide : 'center',
  })

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="ds-layout">
      {layout.rows.map((row, ri) => (
        <div
          key={ri}
          className={[
            'ds-row',
            row.heightMode === 'stretch'     ? 'ds-row--stretch'     : '',
            row.heightMode === 'constrained' ? 'ds-row--constrained' : '',
          ].filter(Boolean).join(' ')}
        >
          {row.tiles.map((item, ti) => {
            // ── Column group (vertical stack) ────────────────────────
            if (typeof item === 'object' && item.col) {
              const colFlex = item.flex || item.col.map(() => 1)
              return (
                <span key={tileKey(item)} style={{ display: 'contents' }}>
                  {ti > 0 && <ResizeHandle rowFlex={row.flex || row.tiles.map(() => 1)}
                    onResize={(d, ppf) => handleFlexChange(ri, ti - 1, d, ppf)} />}
                  <div className="ds-col-group"
                    style={{ flex: row.flex?.[ti] ?? 1, display: 'flex', flexDirection: 'column', minWidth: 0, gap: 0 }}>
                    {item.col.map((tileName, ci) => (
                      <span key={tileName} style={{ display: 'contents' }}>
                        {ci > 0 && <VerticalResizeHandle colFlex={colFlex}
                          onResize={(d, ppf) => handleColFlexChange(ri, ti, ci - 1, d, ppf)} />}
                        <Tile
                          {...tileProps(tileName, ri, row)}
                          flex={colFlex[ci] ?? 1}
                          onUnsplit={() => handleUnsplitFromCol(ri, ti, ci)}
                          canUnsplit={item.col.length > 1}
                        >
                          <SectionErrorBoundary sectionName={tileName}>
                            {children[tileName] || <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>No content for {tileName}</div>}
                          </SectionErrorBoundary>
                        </Tile>
                      </span>
                    ))}
                  </div>
                </span>
              )
            }

            // ── Plain tile ───────────────────────────────────────────
            const tileName = item
            return (
              <span key={tileName} style={{ display: 'contents' }}>
                {ti > 0 && <ResizeHandle rowFlex={row.flex || row.tiles.map(() => 1)}
                  onResize={(d, ppf) => handleFlexChange(ri, ti - 1, d, ppf)} />}
                <Tile
                  {...tileProps(tileName, ri, row)}
                  flex={row.flex?.[ti] ?? 1}
                  onUnsplit={() => handleUnsplit(ri, ti)}
                  canUnsplit={row.tiles.length > 1}
                >
                  <SectionErrorBoundary sectionName={tileName}>
                    {children[tileName] || <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>No content for {tileName}</div>}
                  </SectionErrorBoundary>
                </Tile>
              </span>
            )
          })}
        </div>
      ))}
    </div>
  )
}
