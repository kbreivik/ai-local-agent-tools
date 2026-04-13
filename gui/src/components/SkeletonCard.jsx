/**
 * SkeletonCard — shimmer placeholder for cards while data loads.
 * Matches the visual weight of real cards to prevent layout shift.
 */
export function SkeletonRow({ width = '70%', height = 8 }) {
  return (
    <div style={{
      height, borderRadius: 2,
      background: 'linear-gradient(90deg, var(--bg-3) 25%, var(--bg-2) 50%, var(--bg-3) 75%)',
      backgroundSize: '200% 100%',
      animation: 'ds-shimmer 1.4s infinite',
      width,
    }} />
  )
}

export function SkeletonCard({ rows = 3 }) {
  return (
    <div style={{
      background: 'var(--bg-2)', border: '1px solid var(--border)',
      borderLeft: '3px solid var(--bg-3)', borderRadius: 2,
      padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 8,
    }}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} width={i === 0 ? '45%' : i % 2 === 0 ? '65%' : '80%'} />
      ))}
    </div>
  )
}

export function SkeletonGrid({ count = 4 }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
      gap: 8,
    }}>
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} rows={3 + (i % 2)} />
      ))}
    </div>
  )
}
