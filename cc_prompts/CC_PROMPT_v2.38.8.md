# CC PROMPT — v2.38.8 — fix(ui): wrap toolbox in CollapsibleSection — collapsed by default

## What this does

The tag filter bar and tool/skill list in CommandPanel are rendered as bare divs
directly after `<RecentTasks />` — no collapsible wrapper. This causes the entire
list (~100 tools/skills with tag pills) to appear inline and expanded at all times,
overwhelming the task input area. Same issue that Templates and Recent had before
v2.37.0 fixed them.

Fix: import `CollapsibleSection` and wrap the tag filter bar + tool list in a
single collapsible with `storageKey='toolbox'` and `defaultOpen={false}`.
Label: "TOOLBOX" with item count badge.

Version bump: 2.38.7 → 2.38.8.

---

## Change 1 — `gui/src/components/CommandPanel.jsx` — import CollapsibleSection

Locate the imports at the top (line ~1–10). Add CollapsibleSection import:

```javascript
import { fetchTools, invokeTool, runAgent, fetchSkills, executeSkill } from '../api'
```

Replace with:

```javascript
import { fetchTools, invokeTool, runAgent, fetchSkills, executeSkill } from '../api'
import CollapsibleSection from './CollapsibleSection'
```

---

## Change 2 — `gui/src/components/CommandPanel.jsx` — wrap toolbox

Locate the tag filter bar block. It starts just after `<RecentTasks />` with a
comment and a div containing the tag buttons:

```jsx
        {/* Tag filter bar — scrolls with content in v2.38.2 (was shrink-0
            sticky before, which contributed to height starvation). */}
        <div className={`flex gap-1 border-b border-slate-700 flex-wrap items-center ${isTab ? 'px-4 py-2' : 'px-3 py-2'}`}>
```

And ends after the tool list closing div:

```jsx
        </div>
      </div>
    </div>
  )
```

Replace everything from the tag filter bar comment through to (and including) the
tool list closing `</div>` with the wrapped version below. The outer
`</div>` (scroll region) and `</div>` (main container) stay untouched.

```jsx
        {/* TOOLBOX — tag filter + tool/skill list, collapsed by default */}
        <CollapsibleSection
          storageKey="toolbox"
          defaultOpen={false}
          label={`TOOLBOX${items.length > 0 ? ` (${items.length})` : ''}`}
        >
          {/* Tag filter bar */}
          <div className={`flex gap-1 border-b border-slate-700 flex-wrap items-center ${isTab ? 'px-4 py-2' : 'px-3 py-2'}`}>
            {allTags.map(tag => (
              <button
                key={tag}
                onClick={() => setSelectedTags(prev => {
                  const next = new Set(prev)
                  next.has(tag) ? next.delete(tag) : next.add(tag)
                  return next
                })}
                className={`text-xs px-2 py-0.5 rounded transition-colors ${
                  selectedTags.has(tag)
                    ? 'bg-blue-600 text-white'
                    : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
                }`}
              >
                {humanizeCategory(tag)}
              </button>
            ))}
            {selectedTags.size > 0 && (
              <button
                onClick={() => setSelectedTags(new Set())}
                className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-500 hover:text-slate-300 ml-1"
              >
                ✕ clear
              </button>
            )}
            {allTags.length > 0 && (
              <div className="ml-auto flex items-center gap-0 border border-slate-600 rounded overflow-hidden text-xs shrink-0">
                <button
                  onClick={() => setAndMode(false)}
                  className={`px-2 py-0.5 transition-colors ${!andMode ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
                >
                  OR
                </button>
                <button
                  onClick={() => setAndMode(true)}
                  className={`px-2 py-0.5 transition-colors ${andMode ? 'bg-blue-600 text-white' : 'bg-slate-800 text-slate-400 hover:bg-slate-700'}`}
                >
                  AND
                </button>
              </div>
            )}
          </div>

          {/* Tool/skill list */}
          <div className={isTab ? 'px-4 py-3' : 'px-3 py-2'}>
            {loading && <p className="text-xs text-slate-500 animate-pulse">Loading…</p>}
            {!loading && visible.length === 0 && (
              <p className="text-xs text-slate-600">No items match the selected tags.</p>
            )}
            <div className={isTab ? 'grid grid-cols-2 gap-x-4' : ''}>
              {visible.map(item => (
                <ToolCard key={item.name} tool={item} onResult={onResult} />
              ))}
            </div>
          </div>
        </CollapsibleSection>
```

---

## Version bump

Update `VERSION` file: `2.38.7` → `2.38.8`

---

## Commit

```
git add -A
git commit -m "fix(ui): v2.38.8 wrap toolbox in CollapsibleSection — collapsed by default"
git push origin main
```

Then deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
