/**
 * DashboardLayout — renders a configurable tile grid from layout.rows.
 * Supports drag-reorder, split/unsplit, collapse, resize, and heightMode.
 *
 * Props:
 *   layout      — { rows, collapsed, prefs }
 *   onRowsChange(rows)       — called when rows are reordered/split/unsplit
 *   onCollapsedChange(tile)  — called to toggle collapse on a tile
 *   children    — map of tile-name → React node (section content)
 */
import { useState, useRef, useCallback } from 'react'

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

function Tile({ name, flex, collapsed, heightMode, onDragStart, onDragOver, onDrop,
                onCollapse, onSplit, onUnsplit, onHeightModeToggle, canUnsplit,
                splitCandidates, children, draggingOver }) {
  const meta = TILE_META[name] || { icon: '▪', badge: '' }
  const [splitMenuOpen, setSplitMenuOpen] = useState(false)
  const classes = [
    'ds-tile',
    collapsed ? 'collapsed' : '',
    draggingOver ? 'drag-over' : '',
  ].filter(Boolean).join(' ')

  return (
    <div
      className={classes}
      style={{ flex: flex ?? 1 }}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData('text/plain', name)
        e.dataTransfer.effectAllowed = 'move'
        onDragStart(name)
      }}
      onDragOver={(e) => { e.preventDefault(); onDragOver?.(name) }}
      onDrop={(e) => { e.preventDefault(); onDrop?.(name) }}
    >
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
            title={heightMode === 'constrained' ? 'Switch to auto height' : 'Constrain height (internal scroll)'}
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

  // Compute split candidates for each row (tiles in single-tile rows, not in current row)
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

  const handleDrop = useCallback((targetTile) => {
    if (!dragSource || dragSource === targetTile) {
      setDragSource(null)
      setDragOverTarget(null)
      return
    }

    const newRows = layout.rows.map(row => ({
      tiles: [...row.tiles],
      ...(row.flex ? { flex: [...row.flex] } : {}),
      ...(row.heightMode ? { heightMode: row.heightMode } : {}),
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
      setDragSource(null)
      setDragOverTarget(null)
      return
    }

    if (srcRowIdx === tgtRowIdx) {
      const row = newRows[srcRowIdx]
      ;[row.tiles[srcTileIdx], row.tiles[tgtTileIdx]] = [row.tiles[tgtTileIdx], row.tiles[srcTileIdx]]
      if (row.flex) {
        ;[row.flex[srcTileIdx], row.flex[tgtTileIdx]] = [row.flex[tgtTileIdx], row.flex[srcTileIdx]]
      }
    } else {
      // Move source row to target row's position
      const [srcRow] = newRows.splice(srcRowIdx, 1)
      const adjustedTgt = tgtRowIdx > srcRowIdx ? tgtRowIdx - 1 : tgtRowIdx
      newRows.splice(adjustedTgt, 0, srcRow)
    }

    onRowsChange(newRows)
    setDragSource(null)
    setDragOverTarget(null)
  }, [dragSource, layout.rows, onRowsChange])

  const handleSplit = useCallback((rowIdx, targetTileName) => {
    const currentRow = layout.rows[rowIdx]
    // Find which row the target tile is in
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
            heightMode: row.heightMode || 'auto',
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
          heightMode: row.heightMode || 'auto',
        })
        newRows.push({ tiles: [tileName], heightMode: 'auto' })
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
                onDragOver={setDragOverTarget}
                onDrop={handleDrop}
                onCollapse={() => onCollapsedChange(tileName)}
                onSplit={(target) => handleSplit(ri, target)}
                onUnsplit={() => handleUnsplit(ri, ti)}
                onHeightModeToggle={() => handleHeightModeToggle(ri)}
                canUnsplit={row.tiles.length > 1}
                splitCandidates={getSplitCandidates(ri)}
                draggingOver={dragOverTarget === tileName && dragSource !== tileName}
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
