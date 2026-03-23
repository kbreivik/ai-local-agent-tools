# Skills in Commands — Tag Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generated skills automatically appear in the Commands tab with a multi-select tag filter bar and AND/OR toggle.

**Architecture:** Frontend-only change. `CommandPanel.jsx` fetches `/api/tools` and `/api/skills` in parallel, normalises both into a unified item shape, derives tags per item, and replaces the single-select category filter with a multi-select tag bar plus AND/OR toggle. `ToolCard` gains a `source`-aware invoke path and an amber `generated` badge for skills.

**Tech Stack:** React 18, Tailwind CSS, existing `fetchSkills`/`executeSkill` from `gui/src/api.js`

**Spec:** `docs/superpowers/specs/2026-03-23-skills-in-commands-tag-filtering.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `gui/src/components/CommandPanel.jsx` | All changes — helpers, ToolCard, fetch/merge, filter bar |

No other files change. `gui/src/api.js` already exports `fetchSkills` and `executeSkill`.

---

## Task 1: Helper functions and CATEGORY_COLOR expansion

**Files:**
- Modify: `gui/src/components/CommandPanel.jsx` (top ~35 lines)

This task adds three pure helpers and expands the colour map. No behaviour changes yet.

### Background

`CommandPanel.jsx` currently has this at the top (lines 1–30):
```js
import { useEffect, useState } from 'react'
import { fetchTools, invokeTool, runAgent } from '../api'
// ...

const CATEGORY_COLOR = {
  swarm:         'bg-blue-900 text-blue-300',
  kafka:         'bg-purple-900 text-purple-300',
  orchestration: 'bg-amber-900 text-amber-300',
  elastic:       'bg-teal-900 text-teal-300',
  network:       'bg-green-900 text-green-300',
}
```

We will:
1. Add `fetchSkills`, `executeSkill` to the import from `../api`
2. Expand `CATEGORY_COLOR` with skill/service entries
3. Add `normaliseSkillParams()` helper
4. Add `deriveTags()` helper

- [ ] **Step 1: Update the import line**

Find line 2 in `gui/src/components/CommandPanel.jsx`:
```js
import { fetchTools, invokeTool, runAgent } from '../api'
```
Replace with:
```js
import { fetchTools, invokeTool, runAgent, fetchSkills, executeSkill } from '../api'
```

- [ ] **Step 2: Expand CATEGORY_COLOR**

Find the `CATEGORY_COLOR` const block and replace it entirely:
```js
const CATEGORY_COLOR = {
  // built-in tool categories
  swarm:         'bg-blue-900 text-blue-300',
  kafka:         'bg-purple-900 text-purple-300',
  orchestration: 'bg-amber-900 text-amber-300',
  elastic:       'bg-teal-900 text-teal-300',
  network:       'bg-green-900 text-green-300',
  docker:        'bg-blue-900 text-blue-300',
  // skill categories
  compute:       'bg-sky-900 text-sky-300',
  monitoring:    'bg-cyan-900 text-cyan-300',
  storage:       'bg-violet-900 text-violet-300',
  general:       'bg-slate-700 text-slate-300',
  // common service names from generated skills
  proxmox:       'bg-orange-900 text-orange-300',
  fortigate:     'bg-red-900 text-red-300',
  truenas:       'bg-indigo-900 text-indigo-300',
}
```

- [ ] **Step 3: Add normaliseSkillParams helper**

After the `CATEGORY_COLOR` block, add:
```js
// ── Skill normalisation ───────────────────────────────────────────────────────

function normaliseSkillParams(parameters) {
  const props    = parameters?.properties ?? {}
  const required = parameters?.required   ?? []
  return Object.entries(props).map(([name, schema]) => ({
    name,
    type:        schema.type        ?? 'string',
    description: schema.description ?? '',
    required:    required.includes(name),
    default:     schema.default     ?? '',
  }))
}

function deriveTags(item) {
  if (item.source === 'skill') {
    const parts = [item._compat?.service, item.category].filter(Boolean)
    return parts.length ? [...new Set(parts)] : ['general']
  }
  return [item.category || 'general']
}
```

- [ ] **Step 4: Build to confirm no syntax errors**

```bash
cd gui && npm run build 2>&1 | tail -10
```
Expected: `✓ built in Xs` with no errors.

- [ ] **Step 5: Commit**

```bash
git add gui/src/components/CommandPanel.jsx
git commit -m "feat(gui): add skill normalisation helpers and expand CATEGORY_COLOR"
git push
```

---

## Task 2: ToolCard — source-aware invoke and generated badge

**Files:**
- Modify: `gui/src/components/CommandPanel.jsx` (`ToolCard` function, lines ~107–193)

### Background

`ToolCard` currently starts like:
```js
function ToolCard({ tool, onResult }) {
  // ...
  const execute = async () => {
    setBusy(true)
    setResult(null)
    try {
      const r = await invokeTool(tool.name, params)   // ← hardcoded
```

And the header row:
```jsx
<span className={`text-xs px-1.5 py-0.5 rounded font-mono shrink-0 ${badge}`}>
  {humanizeCategory(tool.category)}
</span>
<span className="text-sm text-slate-200 flex-1">{humanizeTool(tool.name)}</span>
```

Changes:
1. `execute()` branches on `tool.source`
2. Header gets an amber `generated` badge when `tool.source === 'skill'`

- [ ] **Step 1: Update execute() to branch on source**

Find inside `ToolCard`:
```js
      const r = await invokeTool(tool.name, params)
```
Replace with:
```js
      const r = tool.source === 'skill'
        ? await executeSkill(tool.name, params)
        : await invokeTool(tool.name, params)
```

- [ ] **Step 2: Add generated badge to ToolCard header**

Find in `ToolCard`:
```jsx
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono shrink-0 ${badge}`}>
          {humanizeCategory(tool.category)}
        </span>
        <span className="text-sm text-slate-200 flex-1">{humanizeTool(tool.name)}</span>
```
Replace with:
```jsx
        <span className={`text-xs px-1.5 py-0.5 rounded font-mono shrink-0 ${badge}`}>
          {humanizeCategory(tool.category)}
        </span>
        {tool.source === 'skill' && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-amber-900 text-amber-300 shrink-0">
            generated
          </span>
        )}
        <span className="text-sm text-slate-200 flex-1">{humanizeTool(tool.name)}</span>
```

- [ ] **Step 3: Build to confirm no errors**

```bash
cd gui && npm run build 2>&1 | tail -10
```
Expected: `✓ built in Xs`.

- [ ] **Step 4: Commit**

```bash
git add gui/src/components/CommandPanel.jsx
git commit -m "feat(gui): source-aware invoke and generated badge in ToolCard"
git push
```

---

## Task 3: CommandPanel — parallel fetch and unified items list

**Files:**
- Modify: `gui/src/components/CommandPanel.jsx` (`CommandPanel` function state + useEffect)

### Background

`CommandPanel` currently has:
```js
  const [tools, setTools]     = useState([])
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState('all')

  // ...

  useEffect(() => {
    fetchTools()
      .then(setTools)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const categories = ['all', ...new Set(tools.map(t => t.category))]
  const visible = category === 'all' ? tools : tools.filter(t => t.category === category)
```

And the tool list render:
```jsx
          {visible.map(tool => (
            <ToolCard key={tool.name} tool={tool} onResult={onResult} />
          ))}
```

Changes:
1. Replace `tools` state with `items` — a unified array of normalised tool+skill objects
2. Parallel fetch on mount
3. Normalise skills and derive tags for all items
4. Sort: tools first (alpha), then skills (alpha)
5. Remove the old `categories` and `visible` derivations (Task 4 replaces them)

- [ ] **Step 1: Replace state declarations**

Find:
```js
  const [tools, setTools]     = useState([])
  const [loading, setLoading] = useState(true)
  const [category, setCategory] = useState('all')
```
Replace with:
```js
  const [items,    setItems]   = useState([])
  const [loading,  setLoading] = useState(true)
  const [selectedTags, setSelectedTags] = useState(new Set())
  const [andMode,  setAndMode] = useState(false)
```

- [ ] **Step 2: Verify the compat field name on skill objects**

Before writing the fetch, confirm `compat` is the correct field name:
```bash
grep -n '"compat"' mcp_server/tools/skills/storage/sqlite_backend.py | head -5
```
Expected: lines showing `compat TEXT DEFAULT '{}'` (DB column) and `"compat"` in the row dict. The field is `compat` — confirmed in the DB schema.

- [ ] **Step 3: Replace useEffect with parallel fetch**

Find:
```js
  useEffect(() => {
    fetchTools()
      .then(setTools)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])
```
Replace with:
```js
  useEffect(() => {
    Promise.all([
      fetchTools().catch(() => []),
      fetchSkills().catch(() => []),
    ]).then(([tools, skills]) => {
        const normTools = tools.map(t => ({
          ...t,
          source: 'tool',
          tags: [t.category || 'general'],
        }))
        const normSkills = skills.map(s => ({
          name:        s.name,
          description: s.description ?? '',
          category:    s.category ?? 'general',
          params:      normaliseSkillParams(s.parameters),
          source:      'skill',
          _compat:     s.compat ?? null,  // field is "compat" in DB/API
          tags:        [],
        })).map(s => ({ ...s, tags: deriveTags(s) }))

        const sorted = [
          ...normTools.sort((a, b) => a.name.localeCompare(b.name)),
          ...normSkills.sort((a, b) => a.name.localeCompare(b.name)),
        ]
        setItems(sorted)
      })
      .finally(() => setLoading(false))
  }, [])
```

- [ ] **Step 4: Replace categories/visible derivations**

Find:
```js
  const categories = ['all', ...new Set(tools.map(t => t.category))]
  const visible = category === 'all' ? tools : tools.filter(t => t.category === category)
```
Replace with:
```js
  // Derive sorted tag list: tool-sourced tags first, then skill-only tags
  const toolTags  = new Set(items.filter(i => i.source === 'tool').flatMap(i => i.tags))
  const skillTags = new Set(items.filter(i => i.source === 'skill').flatMap(i => i.tags))
  const allTags   = [
    ...[...toolTags].sort(),
    ...[...skillTags].filter(t => !toolTags.has(t)).sort(),
  ]

  const visible = selectedTags.size === 0
    ? items
    : items.filter(item =>
        andMode
          ? [...selectedTags].every(t => item.tags.includes(t))
          : [...selectedTags].some(t => item.tags.includes(t))
      )
```

- [ ] **Step 5: Update the tool list render**

Find:
```jsx
          {visible.map(tool => (
            <ToolCard key={tool.name} tool={tool} onResult={onResult} />
          ))}
```
Replace with:
```jsx
          {visible.map(item => (
            <ToolCard key={item.name} tool={item} onResult={onResult} />
          ))}
```

- [ ] **Step 6: Update loading count display**

Find the loading indicator area:
```jsx
        {loading && <p className="text-xs text-slate-500 animate-pulse">Loading tools…</p>}
        {!loading && visible.length === 0 && (
          <p className="text-xs text-slate-600">No tools found.</p>
        )}
```
Replace with:
```jsx
        {loading && <p className="text-xs text-slate-500 animate-pulse">Loading…</p>}
        {!loading && visible.length === 0 && (
          <p className="text-xs text-slate-600">No items match the selected tags.</p>
        )}
```

- [ ] **Step 7: Build to confirm no errors**

```bash
cd gui && npm run build 2>&1 | tail -10
```
Expected: `✓ built in Xs`.

- [ ] **Step 8: Commit**

```bash
git add gui/src/components/CommandPanel.jsx
git commit -m "feat(gui): parallel fetch tools+skills, unified items list"
git push
```

---

## Task 4: Multi-select tag filter bar with AND/OR toggle

**Files:**
- Modify: `gui/src/components/CommandPanel.jsx` (filter bar section, ~lines 274–288)

### Background

The current filter bar:
```jsx
      {/* Category filter */}
      <div className={`flex gap-1 border-b border-slate-700 flex-wrap shrink-0 ${isTab ? 'px-4 py-2' : 'px-3 py-2'}`}>
        {categories.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={`text-xs px-2 py-0.5 rounded transition-colors ${
              category === c
                ? 'bg-blue-600 text-white'
                : 'bg-slate-700 text-slate-400 hover:bg-slate-600'
            }`}
          >
            {c === 'all' ? 'All' : humanizeCategory(c)}
          </button>
        ))}
      </div>
```

Replace the entire block with a multi-select tag bar + AND/OR toggle.

- [ ] **Step 1: Replace the filter bar JSX**

Find the full filter bar block above and replace with:
```jsx
      {/* Tag filter bar */}
      <div className={`flex gap-1 border-b border-slate-700 flex-wrap items-center shrink-0 ${isTab ? 'px-4 py-2' : 'px-3 py-2'}`}>
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
```

- [ ] **Step 2: Build to confirm no errors**

```bash
cd gui && npm run build 2>&1 | tail -10
```
Expected: `✓ built in Xs` with no errors.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/CommandPanel.jsx
git commit -m "feat(gui): multi-select tag filter bar with AND/OR toggle in Commands"
git push
```

---

## Task 5: Smoke test and final verification

**Files:** none (read-only verification)

No code changes. Verify the feature end-to-end.

- [ ] **Step 1: Full build passes**

```bash
cd gui && npm run build 2>&1 | tail -5
```
Expected: `✓ built in Xs`, no warnings about undefined variables.

- [ ] **Step 2: Python syntax check (no backend changes but sanity check)**

```bash
python -m py_compile api/routers/skills.py api/routers/tools.py
```
Expected: no output (passes silently).

- [ ] **Step 3: Verify merged list in browser (manual)**

Start the dev server:
```bash
cd gui && npm run dev
```
Open http://localhost:5173, log in, go to Commands tab.

Check:
- [ ] Built-in tools still appear (Swarm, Kafka, etc.)
- [ ] Tag filter buttons appear (Swarm, Kafka, Elastic, Network, Orchestration, …)
- [ ] Generated skills appear below built-in tools with an amber `generated` badge
- [ ] Clicking a tag filters the list (OR mode default)
- [ ] Clicking AND shows only items matching ALL selected tags
- [ ] Clicking OR shows items matching ANY selected tag
- [ ] ✕ clear button removes all selected tags
- [ ] Skills tab is unchanged

- [ ] **Step 4: Final commit if any fixes were made during smoke test**

```bash
git add -A
git diff --cached --stat
# only commit if there were actual fixes
git commit -m "fix(gui): post-smoke-test fixes for tag filter"
git push
```
