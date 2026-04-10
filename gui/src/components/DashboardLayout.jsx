/**
 * DashboardLayout — renders a configurable tile grid from layout.rows.
 * Supports drag-reorder, split/unsplit, collapse, and resize.
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

// All known tiles for split selection
const ALL_TILES = ['PLATFORM', 'COMPUTE', 'CONTAINERS', 'NETWORK', 'STORAGE', 'SECURITY']

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

function Tile({ name, flex, collapsed, onDragStart, onDragOver, onDrop, onCollapse, onSplit, onUnsplit, canUnsplit, children, draggingOver }) {
  const meta = TILE_META[name] || { icon: '▪', badge: '' }
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
        {!canUnsplit && (
          <button
            onClick={(e) => { e.stopPropagation(); onSplit() }}
            style={{ fontSize: 9, color: 'var(--text-3)', cursor: 'pointer', background: 'none', border: 'none', padding: '5px 7px', margin: '-5px -3px', minWidth: 26, minHeight: 26, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            title="Split — add tile to this row"
          >⊞</button>
        )}
        {canUnsplit && (
          <button
            onClick={(e) => { e.stopPropagation(); onUnsplit() }}
            style={{ fontSize: 9, color: 'var(--text-3)', cursor: 'pointer', background: 'none', border: 'none', padding: '5px 7px', margin: '-5px -3px', minWidth: 26, minHeight: 26, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
            title="Unsplit — move to own row"
          >⊟</button>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); onCollapse() }}
          style={{ fontSize: 9, color: 'var(--text-3)', cursor: 'pointer', background: 'none', border: 'none', padding: '5px 7px', margin: '-5px -3px', minWidth: 26, minHeight: 26, display: 'inline-flex', alignItems: 'center', justifyContent: 'center' }}
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

  // All tiles currently placed in rows
  const placedTiles = new Set(layout.rows.flatMap(r => r.tiles))

  const handleDrop = useCallback((targetTile) => {
    if (!dragSource || dragSource === targetTile) {
      setDragSource(null)
      setDragOverTarget(null)
      return
    }

    const newRows = layout.rows.map(row => ({
      tiles: [...row.tiles],
      ...(row.flex ? { flex: [...row.flex] } : {}),
    }))

    // Find source and target positions
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
      // Swap within same row
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

  const handleSplit = useCallback((rowIdx, tileIdx) => {
    // Find a tile not in this row to add
    const currentRow = layout.rows[rowIdx]
    // Find tiles that are alone in their row (candidates to merge)
    const candidates = []
    for (let ri = 0; ri < layout.rows.length; ri++) {
      if (ri === rowIdx) continue
      if (layout.rows[ri].tiles.some(t => currentRow.tiles.includes(t))) continue
      if (layout.rows[ri].tiles.length === 1) {
        candidates.push({ tile: layout.rows[ri].tiles[0], rowIdx: ri })
      }
    }
    if (candidates.length === 0) return

    // Pick the next tile alphabetically after current
    const currentTile = currentRow.tiles[tileIdx]
    candidates.sort((a, b) => a.tile.localeCompare(b.tile))
    const pick = candidates.find(c => c.tile > currentTile) || candidates[0]

    const newRows = layout.rows
      .filter((_, ri) => ri !== pick.rowIdx) // remove source row
      .map(row => {
        if (row === currentRow) {
          return {
            tiles: [...row.tiles, pick.tile],
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
        // Remove tile from this row
        const remainingTiles = row.tiles.filter((_, ti) => ti !== tileIdx)
        const remainingFlex = row.flex ? row.flex.filter((_, ti) => ti !== tileIdx) : undefined
        newRows.push({
          tiles: remainingTiles,
          ...(remainingFlex && remainingFlex.length > 1 ? { flex: remainingFlex } : {}),
        })
        // Insert new row for unsplit tile
        newRows.push({ tiles: [tileName] })
      } else {
        newRows.push({ ...layout.rows[ri] })
      }
    }

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
        <div key={ri} className="ds-row">
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
                onDragStart={setDragSource}
                onDragOver={setDragOverTarget}
                onDrop={handleDrop}
                onCollapse={() => onCollapsedChange(tileName)}
                onSplit={() => handleSplit(ri, ti)}
                onUnsplit={() => handleUnsplit(ri, ti)}
                canUnsplit={row.tiles.length > 1}
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
