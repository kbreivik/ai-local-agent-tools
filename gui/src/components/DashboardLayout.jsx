/**
 * DashboardLayout — renders a configurable tile grid from layout.rows.
 * Supports drag-reorder, drag-to-split (position-aware drop zones),
 * split/unsplit, collapse, resize, and auto-fit heightMode.
 *
 * Props:
 *   layout      — { rows, collapsed, prefs }
 *   onRowsChange(rows)       — called when rows are reordered/split/unsplit
 *   onCollapsedChange(tile)  — called to toggle collapse on a tile
 *   children    — map of tile-name → React node (section content)
 */
import { useState, useRef, useCallback, useLayoutEffect } from 'react'

const TILE_META = {
  PLATFORM:   { icon: '⬡', badge: 'INTERNAL' },
  COMPUTE:    { icon: '◈', badge: 'HYPERVISORS' },
  CONTAINERS: { icon: '⊟', badge: 'DOCKER' },
  NETWORK:    { icon: '◉', badge: 'INFRA' },
  STORAGE:    { icon: '⊠', badge: 'DATA' },
  SECURITY:   { icon: '⊛', badge: 'SOC' },
}

const ACTION_BTN = {
  fontSize: 9, cursor: 'pointer', background: 'none', border: 'none',
  padding: '5px 7px', margin: '-5px -3px', minWidth: 26, minHeight: 26,
  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
}

function ResizeHandle({ onResize, rowFlex }) {
  const handleRef = useRef(null)

  const onMouseDown = useCallback((e) => {
    e.preventDefault()
    const startX = e.clientX
    const rowEl = handleRef.current?.closest('.ds-row')
    const rowWidth = rowEl ? rowEl.getBoundingClientRect().width : 1000
    const totalFlex = (rowFlex || []).reduce((a, b) => a + b, 0) || 1
    const pixelPerFlex = rowWidth / totalFlex
    const onMove = (me) => {
      onResize(me.clientX - startX, pixelPerFlex)
    }
    const onUp = () => {
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [onResize, rowFlex])

  return (
    <div
      ref={handleRef}
      className="ds-resize-handle"
      onMouseDown={onMouseDown}
    />
  )
}

function Tile({ name, flex, collapsed, heightMode, dragDropSide,
                onDragStart, onDragOver, onDrop,
                onCollapse, onSplit, onUnsplit, onHeightModeToggle, canUnsplit,
                splitCandidates, children, draggingOver }) {
  const meta = TILE_META[name] || { icon: '▪', badge: '' }
  const [splitMenuOpen, setSplitMenuOpen] = useState(false)
  const classes = [
    'ds-tile',
    collapsed ? 'collapsed' : '',
  ].filter(Boolean).join(' ')

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
      onDragOver={(e) => {
        e.preventDefault()
        const rect = e.currentTarget.getBoundingClientRect()
        const relX = (e.clientX - rect.left) / rect.width
        const side = relX < 0.3 ? 'left' : relX > 0.7 ? 'right' : 'center'
        onDragOver?.(name, side)
      }}
      onDrop={(e) => {
        e.preventDefault()
        const rect = e.currentTarget.getBoundingClientRect()
        const relX = (e.clientX - rect.left) / rect.width
        const side = relX < 0.3 ? 'left' : relX > 0.7 ? 'right' : 'center'
        onDrop?.(name, side)
      }}
    >
      {/* Drop zone overlay */}
      {draggingOver && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 10, pointerEvents: 'none',
          display: 'flex', borderRadius: 0,
        }}>
          <div style={{
            width: '30%', height: '100%',
            background: dragDropSide === 'left' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderLeft: dragDropSide === 'left' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.1s',
          }} />
          <div style={{
            flex: 1, height: '100%',
            background: dragDropSide === 'center' ? 'rgba(0,200,238,0.07)' : 'transparent',
            transition: 'all 0.1s',
          }} />
          <div style={{
            width: '30%', height: '100%',
            background: dragDropSide === 'right' ? 'rgba(0,200,238,0.18)' : 'transparent',
            borderRight: dragDropSide === 'right' ? '3px solid var(--cyan)' : 'none',
            transition: 'all 0.1s',
          }} />
        </div>
      )}
      <div className="ds-tile-hdr">
        <span style={{ cursor: 'grab', color: 'var(--text-3)', fontSize: 11 }}>⠿</span>
        <span style={{ fontSize: 11 }}>{meta.icon}</span>
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 700, fontSize: 11, color: 'var(--text-1)', letterSpacing: 0.5 }}>
          {name}
        </span>
        {meta.badge && (
          <span style={{ fontSize: 7, fontFamily: 'var(--font-mono)', padding: '1px 4px', background: 'var(--bg-3)', color: 'var(--text-3)', borderRadius: 2, letterSpacing: 1 }}>
            {meta.badge}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {/* Split button with dropdown picker */}
        {!canUnsplit && splitCandidates?.length > 0 && (
          <div style={{ position: 'relative', display: 'inline-flex' }}>
            <button
              onClick={(e) => { e.stopPropagation(); setSplitMenuOpen(o => !o) }}
              style={{ ...ACTION_BTN, color: 'var(--text-3)' }}
              title="Split — add tile to this row"
            >⊞</button>
            {splitMenuOpen && (
              <div style={{
                position: 'absolute', top: '100%', right: 0, zIndex: 50,
                background: 'var(--bg-2)', border: '1px solid var(--border)',
                borderRadius: 2, minWidth: 120, marginTop: 2,
              }}>
                {splitCandidates.map(c => (
                  <button key={c} onClick={(e) => { e.stopPropagation(); onSplit(c); setSplitMenuOpen(false) }}
                    style={{ display: 'block', width: '100%', textAlign: 'left',
                             padding: '4px 8px', fontSize: 9, fontFamily: 'var(--font-mono)',
                             background: 'none', border: 'none', color: 'var(--text-2)', cursor: 'pointer' }}
                    onMouseOver={e => e.currentTarget.style.background = 'var(--bg-3)'}
                    onMouseOut={e => e.currentTarget.style.background = 'none'}
                  >{c}</button>
                ))}
              </div>
            )}
          </div>
        )}
        {canUnsplit && (
          <button
            onClick={(e) => { e.stopPropagation(); onUnsplit() }}
            style={{ ...ACTION_BTN, color: 'var(--text-3)' }}
            title="Unsplit — move to own row"
          >⊟</button>
        )}
        {canUnsplit && (
          <button
            onClick={(e) => { e.stopPropagation(); onHeightModeToggle() }}
            style={{ ...ACTION_BTN, color: heightMode === 'constrained' ? 'var(--cyan)' : 'var(--text-3)' }}
            title={heightMode === 'constrained' ? 'Height: capped — click for auto' : 'Height: auto — click to cap'}
          >{heightMode === 'constrained' ? '⊡' : '⊞'}</button>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onCollapse() }}
          style={{ ...ACTION_BTN, color: 'var(--text-3)' }}
          title={collapsed ? 'Expand' : 'Collapse'}
        >{collapsed ? '▶' : '▼'}</button>
      </div>
      {!collapsed && (
        <div className="ds-tile-body">
          {children}
        </div>
      )}
    </div>
  )
}

export default function DashboardLayout({ layout, onRowsChange, onCollapsedChange, children }) {
  const [dragSource, setDragSource] = useState(null)
  const [dragOverTarget, setDragOverTarget] = useState(null)
  const [dragDropSide, setDragDropSide] = useState('center')

  // ── Auto-fit height detection ──────────────────────────────────────────
  const tileArrangementKey = JSON.stringify(layout.rows.map(r => r.tiles.join(',')))
  useLayoutEffect(() => {
    const dsRows = document.querySelectorAll('.ds-row')
    let changed = false
    const newRows = layout.rows.map((row, ri) => {
      if (row.heightMode === 'constrained') return row
      if (row.tiles.length < 2) {
        if ((row.heightMode || 'auto') === 'auto') return row
        changed = true
        return { ...row, heightMode: 'auto' }
      }
      const rowEl = dsRows[ri]
      if (!rowEl) return row
      const bodies = Array.from(rowEl.querySelectorAll(':scope > span > .ds-tile .ds-tile-body, :scope > .ds-tile .ds-tile-body'))
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
  }, [tileArrangementKey]) // eslint-disable-line react-hooks/exhaustive-deps

  // Compute split candidates for each row
  const getSplitCandidates = useCallback((rowIdx) => {
    const currentRow = layout.rows[rowIdx]
    const candidates = []
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) continue
      if (layout.rows[ri].tiles.some(t => currentRow.tiles.includes(t))) continue
      if (layout.rows[ri].tiles.length === 1) {
        candidates.push(layout.rows[ri].tiles[0])
      }
    }
    return candidates.sort()
  }, [layout.rows])

  const handleDragOver = useCallback((tileName, side) => {
    setDragOverTarget(tileName)
    setDragDropSide(side)
  }, [])

  const handleDrop = useCallback((targetTile, side) => {
    if (!dragSource || dragSource === targetTile) {
      setDragSource(null); setDragOverTarget(null); setDragDropSide('center')
      return
    }

    const newRows = layout.rows.map(row => ({
      tiles: [...row.tiles],
      ...(row.flex       ? { flex: [...row.flex] }             : {}),
      ...(row.heightMode ? { heightMode: row.heightMode }       : {}),
    }))

    let srcRowIdx = -1, srcTileIdx = -1
    let tgtRowIdx = -1, tgtTileIdx = -1
    for (let ri = 0; ri < newRows.length; ri++) {
      const si = newRows[ri].tiles.indexOf(dragSource)
      if (si !== -1) { srcRowIdx = ri; srcTileIdx = si }
      const ti = newRows[ri].tiles.indexOf(targetTile)
      if (ti !== -1) { tgtRowIdx = ri; tgtTileIdx = ti }
    }

    if (srcRowIdx === -1 || tgtRowIdx === -1) {
      setDragSource(null); setDragOverTarget(null); setDragDropSide('center')
      return
    }

    if (side === 'left' || side === 'right') {
      // ── Auto-split: pull source out, insert into target's row ──────────
      // 1. Remove source tile from its origin row
      newRows[srcRowIdx].tiles.splice(srcTileIdx, 1)
      if (newRows[srcRowIdx].flex) newRows[srcRowIdx].flex.splice(srcTileIdx, 1)

      // 2. Drop empty origin rows
      const filtered = newRows.filter(r => r.tiles.length > 0)

      // 3. Find updated target row index after possible row removal
      let newTgtRowIdx = -1, newTgtTileIdx = -1
      for (let ri = 0; ri < filtered.length; ri++) {
        const ti = filtered[ri].tiles.indexOf(targetTile)
        if (ti !== -1) { newTgtRowIdx = ri; newTgtTileIdx = ti; break }
      }
      if (newTgtRowIdx === -1) {
        onRowsChange(filtered)
        setDragSource(null); setDragOverTarget(null); setDragDropSide('center')
        return
      }

      // 4. Insert source into target row at correct side
      const insertAt = side === 'left' ? newTgtTileIdx : newTgtTileIdx + 1
      filtered[newTgtRowIdx].tiles.splice(insertAt, 0, dragSource)

      // 5. Recalculate flex — equal distribution across all tiles in row
      const tileCount = filtered[newTgtRowIdx].tiles.length
      filtered[newTgtRowIdx].flex = Array(tileCount).fill(1)
      delete filtered[newTgtRowIdx].heightMode // auto-fit will recalculate

      onRowsChange(filtered)

    } else {
      // ── Center zone: row reorder (existing behaviour) ───────────────────
      if (srcRowIdx === tgtRowIdx) {
        const row = newRows[srcRowIdx]
        ;[row.tiles[srcTileIdx], row.tiles[tgtTileIdx]] =
          [row.tiles[tgtTileIdx], row.tiles[srcTileIdx]]
        if (row.flex) {
          ;[row.flex[srcTileIdx], row.flex[tgtTileIdx]] =
            [row.flex[tgtTileIdx], row.flex[srcTileIdx]]
        }
      } else {
        const [srcRow] = newRows.splice(srcRowIdx, 1)
        const adjustedTgt = tgtRowIdx > srcRowIdx ? tgtRowIdx - 1 : tgtRowIdx
        newRows.splice(adjustedTgt, 0, srcRow)
      }
      onRowsChange(newRows)
    }

    setDragSource(null)
    setDragOverTarget(null)
    setDragDropSide('center')
  }, [dragSource, layout.rows, onRowsChange])

  const handleSplit = useCallback((rowIdx, targetTileName) => {
    const currentRow = layout.rows[rowIdx]
    let pickRowIdx = -1
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) continue
      if (layout.rows[ri].tiles.length === 1 && layout.rows[ri].tiles[0] === targetTileName) {
        pickRowIdx = ri
        break
      }
    }
    if (pickRowIdx === -1) return

    const newRows = layout.rows
      .filter((_, ri) => ri !== pickRowIdx)
      .map(row => {
        if (row === currentRow) {
          return {
            tiles: [...row.tiles, targetTileName],
            flex: [...(row.flex || row.tiles.map(() => 1)), 2],
          }
        }
        return { ...row }
      })

    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  const handleUnsplit = useCallback((rowIdx, tileIdx) => {
    const row = layout.rows[rowIdx]
    if (row.tiles.length <= 1) return

    const tileName = row.tiles[tileIdx]
    const newRows = []

    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) {
        const remainingTiles = row.tiles.filter((_, ti) => ti !== tileIdx)
        const remainingFlex = row.flex ? row.flex.filter((_, ti) => ti !== tileIdx) : undefined
        newRows.push({
          tiles: remainingTiles,
          ...(remainingFlex && remainingFlex.length > 1 ? { flex: remainingFlex } : {}),
        })
        newRows.push({ tiles: [tileName] })
      } else {
        newRows.push({ ...layout.rows[ri] })
      }
    }

    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  const handleHeightModeToggle = useCallback((rowIdx) => {
    const newRows = layout.rows.map((r, ri) => {
      if (ri !== rowIdx) return r
      const current = r.heightMode || 'auto'
      return { ...r, heightMode: current === 'constrained' ? 'auto' : 'constrained' }
    })
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

  const handleFlexChange = useCallback((rowIdx, tileIdx, delta, pixelPerFlex) => {
    const row = layout.rows[rowIdx]
    if (row.tiles.length < 2) return

    const flex = row.flex ? [...row.flex] : row.tiles.map(() => 1)
    const flexDelta = delta / (pixelPerFlex || 100)

    flex[tileIdx] = Math.max(0.5, flex[tileIdx] + flexDelta)
    if (tileIdx + 1 < flex.length) {
      flex[tileIdx + 1] = Math.max(0.5, flex[tileIdx + 1] - flexDelta)
    }

    const newRows = layout.rows.map((r, ri) =>
      ri === rowIdx ? { ...r, flex } : r
    )
    onRowsChange(newRows)
  }, [layout.rows, onRowsChange])

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
          {row.tiles.map((tileName, ti) => (
            <span key={tileName} style={{ display: 'contents' }}>
              {ti > 0 && (
                <ResizeHandle
                  rowFlex={row.flex || row.tiles.map(() => 1)}
                  onResize={(delta, ppf) => handleFlexChange(ri, ti - 1, delta, ppf)}
                />
              )}
              <Tile
                name={tileName}
                flex={row.flex?.[ti] ?? 1}
                collapsed={layout.collapsed?.includes(tileName)}
                heightMode={row.heightMode || 'auto'}
                onDragStart={setDragSource}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
                onCollapse={() => onCollapsedChange(tileName)}
                onSplit={(target) => handleSplit(ri, target)}
                onUnsplit={() => handleUnsplit(ri, ti)}
                onHeightModeToggle={() => handleHeightModeToggle(ri)}
                canUnsplit={row.tiles.length > 1}
                splitCandidates={getSplitCandidates(ri)}
                draggingOver={dragOverTarget === tileName && dragSource !== tileName}
                dragDropSide={dragOverTarget === tileName && dragSource !== tileName
                  ? dragDropSide : 'center'}
              >
                {children[tileName] || (
                  <div style={{ padding: 12, color: 'var(--text-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
                    No content for {tileName}
                  </div>
                )}
              </Tile>
            </span>
          ))}
        </div>
      ))}
    </div>
  )
}
