# CC PROMPT — v2.24.3 — Fix SubtaskOfferBanner buttons clipped by overflow-hidden parent

## What this does
The `SubtaskOfferBanner` uses `flexWrap: 'wrap'` but its ancestor div has `overflow-hidden`,
so any wrapped row is clipped and the "Run Sub-agent", "Manual Runbook", and "×" buttons are
never visible. Fix: constrain the task text span to a `maxWidth` with `textOverflow: ellipsis`
and `whiteSpace: nowrap` so all elements stay on a single line. Version bump: v2.24.2 → v2.24.3

## Change 1 — gui/src/components/SubtaskOfferBanner.jsx

Find the task text `<span>` (it has `flex: 1, minWidth: 0`):
```jsx
      {/* Task text */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                     color: 'var(--text-2)', flex: 1, minWidth: 0 }}>
        {latest.task?.slice(0, 120)}
        {extra > 0 && (
          <span style={{ color: 'var(--cyan)', marginLeft: 6 }}>+{extra} more</span>
        )}
      </span>
```

Replace with:
```jsx
      {/* Task text */}
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10,
                     color: 'var(--text-2)', maxWidth: 340, minWidth: 0,
                     overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {latest.task?.slice(0, 80)}
        {extra > 0 && (
          <span style={{ color: 'var(--cyan)', marginLeft: 6 }}>+{extra} more</span>
        )}
      </span>
```

Also remove `flexWrap: 'wrap'` from the outer banner `div` style since it is no longer needed
and caused the overflow problem. Find:
```jsx
      flexWrap: 'wrap',
```
Delete that line entirely.

## Version bump
Update VERSION file: v2.24.2 → v2.24.3

## Commit
```
git add -A
git commit -m "fix(SubtaskOfferBanner): cap task text width so action buttons never clip (v2.24.3)"
git push origin main
```
