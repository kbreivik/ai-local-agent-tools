# CC PROMPT — v2.34.7 — fix(ui): version dropdown lost running-version indicator

## Evidence

Screenshot from live use shows the GHCR version dropdown listing all available
tags (2.34.6, 2.34.5, 2.34.4, 2.34.3, ...) but with **no visual indicator of
which version is currently running**. Previous behaviour was: the running
version had a `▶` arrow prefix and a `(running)` text suffix next to the
version label. Now those markers are gone and the user has to read the
closed-dropdown state at the bottom to know which one they're on.

Likely regression from v2.33.10 (full tags list lifted to ServiceCards parent)
or v2.34.3 (pull-bar label changes). Neither explicitly touched the dropdown
option rendering, so it's probably a lost conditional during the lifting.

Version bump: 2.34.6 → 2.34.7

---

## Change 1 — gui/src/components/ServiceCards.jsx (or ContainerCardExpanded)

Locate the tag-dropdown rendering (the `<select>` or `<option>` block, or the
custom dropdown from v2.33.10). Find where each tag is rendered as an option.

Before the regression, the option label was something like:

```jsx
<option value={tag}>
  {tag === runningTag && '▶ '}{tag}{tag === runningTag && ' (running)'}
</option>
```

Or if it's a custom dropdown:

```jsx
<div className="version-row">
  {tag === runningTag && <span className="arrow">▶</span>}
  <span className="tag">{tag}</span>
  {tag === runningTag && <span className="running-label">running</span>}
</div>
```

Restore both markers. The running tag should be detected by comparing each
list entry to the container's currently-deployed tag (from `container.image`
or the `running_version` field the collector populates).

## Change 2 — explicit prop threading

If v2.33.10 lifted the tags list but didn't lift the running-version field
alongside it, the comparison will fail because the parent component doesn't
have `runningTag` in scope. Verify:

- Parent (`ServiceCards.jsx`) passes `runningTag` (or `container.runningVersion`
  or `currentTag`) to the dropdown component as a prop
- Dropdown component accepts and uses it for the comparison

If the field name was renamed at some point, confirm the current name on the
container object (likely `current_tag`, `running_version`, or `image_tag`).

## Change 3 — visual styling

The running-version row should be visually distinct. Use:

```jsx
style={{
  fontWeight: tag === runningTag ? 'bold' : 'normal',
  color: tag === runningTag ? 'var(--accent)' : 'var(--text-1)',
  // optional: background tint
  background: tag === runningTag ? 'var(--accent-dim)' : 'transparent',
}}
```

Keep the arrow+text subtle (`var(--text-3)` for the "running" suffix, not
`var(--accent)`) so the row isn't overwhelming.

## Change 4 — test

`tests/test_version_dropdown.jsx` (or whatever the frontend test pattern is):

```jsx
test('running version is marked in dropdown', () => {
  const { getByText } = render(
    <VersionDropdown tags={['2.34.6', '2.34.5', '2.34.4']} runningTag="2.34.4" />
  )
  const runningRow = getByText('2.34.4').closest('.version-row')
  expect(runningRow.textContent).toContain('▶')
  expect(runningRow.textContent).toContain('running')
})

test('non-running versions have no marker', () => {
  const { getByText } = render(
    <VersionDropdown tags={['2.34.6', '2.34.5', '2.34.4']} runningTag="2.34.4" />
  )
  const otherRow = getByText('2.34.5').closest('.version-row')
  expect(otherRow.textContent).not.toContain('▶')
  expect(otherRow.textContent).not.toContain('running')
})
```

## Version bump
Update `VERSION`: 2.34.6 → 2.34.7

## Commit
```
git add -A
git commit -m "fix(ui): v2.34.7 restore running-version marker in container tag dropdown"
git push origin main
```

## How to test after push
1. Redeploy.
2. Expand any container card with multiple available tags.
3. Open the version dropdown. The currently-running tag must show `▶` prefix
   AND `(running)` or `running` suffix.
4. Other tags must render plain.
5. Pull a different tag, wait for recreate, reopen the dropdown — the marker
   should now be on the new tag.
