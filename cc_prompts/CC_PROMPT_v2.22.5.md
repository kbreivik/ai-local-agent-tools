# CC PROMPT — v2.22.5 — Fix GHCR tag fetch pagination + version status display

## What this does

Two bugs in the hp1_agent container card:

1. **GHCR tag pagination stops too early** — `_fetch_ghcr_tags()` in dashboard.py
   stops fetching pages as soon as it has accumulated 20 semver-matching tags.
   GHCR returns tags alphabetically, so the first 20 semver matches are always
   the OLDEST ones (2.14.0 → 2.19.1). It never reaches 2.20.x, 2.21.x, 2.22.x
   which live on a later page. The CI workflow correctly pushes versioned semver
   tags on every build — the tags exist on GHCR, they're just never fetched.

2. **Status shows "—" instead of "✓ latest"** — when `running_version > tags[0]`
   (running ahead of the highest known tag), `compareSemver` returns 'ahead' which
   falls through to "—" in the status row and shows a spurious "Pull Latest" button.
   The update-status endpoint already correctly reports `update_available: false`
   when digests match. The card should read this signal and show "✓ latest" and
   hide the pull button when the running image IS the latest.

Version bump: 2.22.4 → 2.22.5

---

## Change 1 — api/routers/dashboard.py

### 1a — Remove early-exit from _fetch_ghcr_tags pagination

Find inside `_fetch_ghcr_tags`:

```python
        all_tags.extend(r.json().get("tags") or [])

        if len([t for t in all_tags if semver_re.match(t)]) >= 20:
            break

        # Follow Link header pagination
```

Replace with (remove the early-exit block, keep pagination):

```python
        all_tags.extend(r.json().get("tags") or [])

        # Follow Link header pagination — do NOT stop early.
        # GHCR returns tags alphabetically, so old tags appear before new ones.
        # We must page through ALL tags to find the newest semver versions.
```

### 1b — Increase max pages from 3 to 10

Find:

```python
    for _ in range(3):
```

Replace with:

```python
    for _ in range(10):
```

This allows up to 5000 tags across 10 pages of 500 — more than enough for this repo.

---

## Change 2 — gui/src/components/ServiceCards.jsx

### 2a — Load update-status in ContainerCardExpanded for agent container

In `ContainerCardExpanded`, add a state variable for update status near the other state declarations (after `const [versionPickerOpen, setVersionPickerOpen] = useState(false)`):

```jsx
  const [updateStatus, setUpdateStatus] = useState(null)
```

Add a useEffect to fetch update-status for GHCR images (add after the tags fetch useEffect):

```jsx
  useEffect(() => {
    if (!c.image?.startsWith('ghcr.io/')) return
    fetch(`${BASE}/api/dashboard/update-status`, { headers: { ...authHeaders() } })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (mounted.current && d) setUpdateStatus(d) })
      .catch(() => {})
  }, [c.image])  // eslint-disable-line react-hooks/exhaustive-deps
```

### 2b — Use update-status to determine true "is latest" status

In the version display block inside `ContainerCardExpanded`, find:

```jsx
        {/* Status badge */}
        {c.running_version && (
          <div className="flex justify-between text-[9px] mb-1.5">
            <span className="text-gray-700">Status</span>
            {tagsLoading
              ? <span className="text-gray-700">…</span>
              : tagsError
              ? <span className="text-gray-700">version check unavailable</span>
              : !tags.length
              ? <span className="text-gray-700">no versioned tags</span>
              : severity === 'current'
              ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
              : hasUpdate
              ? <span className={`text-[9px] px-1.5 py-px rounded border ${severity === 'major' ? 'bg-[#1a0808] text-red-400 border-[#3a1010]' : 'bg-[#2a1e05] text-amber-400 border-[#3d2d0a]'}`}>
                  ⬆ {tags[0]} {severity}
                </span>
              : <span className="text-gray-700">—</span>
            }
          </div>
        )}
```

Replace with:

```jsx
        {/* Status badge */}
        {c.running_version && (
          <div className="flex justify-between text-[9px] mb-1.5">
            <span className="text-gray-700">Status</span>
            {tagsLoading
              ? <span className="text-gray-700">…</span>
              : tagsError
              ? <span className="text-gray-700">version check unavailable</span>
              : !tags.length
              // No semver tags on GHCR — fall back to digest comparison
              ? updateStatus?.update_available === false
                ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                : updateStatus?.update_available === true
                ? <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1e05] text-amber-400 border border-[#3d2d0a]">⬆ update available</span>
                : <span className="text-gray-700">no versioned tags</span>
              : severity === 'current'
              ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
              : severity === 'ahead'
              // Running version is NEWER than highest known tag (e.g. GHCR pagination was stale)
              // Trust the digest comparison from update-status as the authoritative signal
              ? updateStatus?.update_available === false
                ? <span className="text-[9px] px-1.5 py-px rounded bg-[#0d1f0d] text-green-400 border border-[#1a3a1a]">✓ latest</span>
                : updateStatus?.update_available === true
                ? <span className="text-[9px] px-1.5 py-px rounded bg-[#2a1e05] text-amber-400 border border-[#3d2d0a]">⬆ update available</span>
                : <span className="text-gray-700">✓ ahead of tagged</span>
              : hasUpdate
              ? <span className={`text-[9px] px-1.5 py-px rounded border ${severity === 'major' ? 'bg-[#1a0808] text-red-400 border-[#3a1010]' : 'bg-[#2a1e05] text-amber-400 border-[#3d2d0a]'}`}>
                  ⬆ {tags[0]} {severity}
                </span>
              : <span className="text-gray-700">—</span>
            }
          </div>
        )}
```

### 2c — Hide the spurious "Pull Latest" button when already on latest

Find the fallback pull button that appears when `severity === 'ahead'`:

```jsx
            {/* Fallback pull when version check unavailable or no tags */}
            {(tagsError || (!tagsLoading && !tags.length) || severity === 'ahead' || severity === 'unknown') && (
              <ActionBtn
                key="pull"
                label="↓ Pull Latest"
                variant={pullColor}
                loading={loading.pull}
                onClick={() => act('pull', pullPath, null, null)}
              />
            )}
```

Replace with:

```jsx
            {/* Fallback pull when version check unavailable or no tags */}
            {(tagsError || (!tagsLoading && !tags.length) || severity === 'ahead' || severity === 'unknown') &&
             updateStatus?.update_available !== false && (
              <ActionBtn
                key="pull"
                label="↓ Pull Latest"
                variant={pullColor}
                loading={loading.pull}
                onClick={() => act('pull', pullPath, null, null)}
              />
            )}
```

The added `&& updateStatus?.update_available !== false` hides the pull button when the
update-status endpoint confirms the running digest matches the latest digest — meaning
no pull is needed even if the semver tags are stale.

---

## Do NOT touch

- Any collector files
- `api/agents/router.py`
- `mcp_server/`

---

## Version bump

Update `VERSION`: `2.22.4` → `2.22.5`

---

## Commit

```bash
git add -A
git commit -m "fix(ui): v2.22.5 GHCR tag pagination + version status display

- _fetch_ghcr_tags: remove early-exit that stopped at 20 semver tags
  GHCR returns tags alphabetically so first 20 are oldest (2.14-2.19.1)
  newer tags (2.20.x-2.22.x) were on later pages never fetched
  Fix: remove early-exit, increase max pages to 10, fetch all tags first
- ContainerCardExpanded: load update-status for GHCR images
- Status badge: 'severity=ahead' + update_available=false → '✓ latest'
  was showing '—' because running version > highest known GHCR semver tag
- Pull Latest button: hidden when update_available=false (digests match)
  was showing spuriously when running version > highest known tag"
git push origin main
```
