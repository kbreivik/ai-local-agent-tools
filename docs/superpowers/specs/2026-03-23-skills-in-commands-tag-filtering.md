# Skills in Commands — Tag Filtering Design

**Date:** 2026-03-23
**Status:** Approved

## Goal

Generated skills automatically appear in the Commands tab alongside built-in MCP tools. The filter bar becomes a multi-select tag system with an AND/OR toggle, so tools and skills can be filtered by service (Proxmox, FortiGate, …) and category (monitoring, compute, …) simultaneously. The Skills tab is unchanged — it remains the dedicated place for lifecycle management (promote, demote, scrap, edit).

## Background

Currently the Commands tab shows only built-in MCP tools fetched from `/api/tools`. Newly generated skills only appear in the Skills tab (`/api/skills`). There is no cross-tab visibility and no way to filter tools by multiple criteria at once.

## Architecture

Frontend-only change. No backend modifications required.

`CommandPanel.jsx` fetches `/api/tools` and `/api/skills` in parallel on mount, normalises both into a shared shape, and renders them in one unified list. Tag derivation, multi-select filtering, and AND/OR logic all live in the component.

## Normalised Item Shape

```js
{
  // shared fields
  name:        string,        // e.g. "proxmox_vm_status"
  description: string,
  params:      Param[],       // [{name, type, required, description, default}]
  category:    string,        // original category value

  // new fields
  source: "tool" | "skill",   // controls which invoke path to use
  tags:   string[],           // derived — see Tag Derivation
}
```

`ToolCard` uses `source` to decide the invoke path. `ToolCard` imports `executeSkill` directly from `../api` (it already imports `invokeTool` from there):
- `"tool"` → `invokeTool(name, params)` via `/api/tools/{name}/invoke`
- `"skill"` → `executeSkill(name, params)` via `/api/skills/{name}/execute`

The branch lives inside `ToolCard`'s `execute` function:
```js
const r = tool.source === 'skill'
  ? await executeSkill(tool.name, params)
  : await invokeTool(tool.name, params)
```

## Tag Derivation

### Built-in tools
```
tags = [tool.category || "general"]
// e.g. swarm tool → ["swarm"], kafka tool → ["kafka"]
// falsy category (null, "", undefined) → ["general"]
```

### Generated skills
```js
const parts = [skill.compat?.service, skill.category].filter(Boolean)
const tags  = parts.length ? [...new Set(parts)] : ['general']
// both present:  ["proxmox", "monitoring"]
// service only:  ["proxmox"]
// category only: ["monitoring"]
// neither:       ["general"]
```

`skill.compat` is the compat object on the skill row; `.service` is the value from `SKILL_META.compat.service` (e.g. `"proxmox"`, `"fortigate"`, `"truenas"`). Already returned by `/api/skills`.

Tag values are lowercased before storage. Display labels are title-cased: `"proxmox"` → `"Proxmox"`.

## Filter Bar

The existing single-select category filter bar is replaced with a multi-select tag bar.

### Behaviour
- Each unique tag across the merged list appears as a toggle button.
- Clicking a tag toggles it active/inactive.
- Multiple tags can be active simultaneously.
- No tags active = show all items (equivalent to current "All").
- Tags are sorted at runtime by derivation: tags that appear on at least one **tool-sourced** item come first (alphabetical), then tags that appear only on skill-sourced items (alphabetical). This is fully derivable from the merged list — no hardcoded category list required.

### AND / OR toggle
A small two-state toggle sits to the right of the tag buttons:

```
[Swarm] [Kafka] [Proxmox] [Monitoring]   AND | OR
```

- **OR (default):** show items where `item.tags` intersects with selected tags (any match).
- **AND:** show items where `item.tags` contains all selected tags.

Toggle state is local component state, resets to OR on panel mount.

## ToolCard Changes

Generated skills render an amber `generated` badge alongside the category badge:

```
[Proxmox] [generated]  Proxmox Vm Status          ▼
```

Everything else in `ToolCard` (param form, execute button, result display, status border colours) is unchanged.

## Skills Tab

Unchanged. Remains the dedicated lifecycle management surface:
- View all skills with status badges
- Promote / demote / scrap / restore
- Execute with param form
- Per-skill result display

## Merged List Sort Order

The merged list is sorted as follows:
1. Tool-sourced items first, skill-sourced items appended.
2. Within each group, items are sorted alphabetically by `name`.

This means existing built-in tools retain their relative positions, and generated skills are appended in alphabetical order below them.

## Data Flow

```
CommandPanel mounts
  ├── fetchTools()  → /api/tools   → built-in tool list
  └── fetchSkills() → /api/skills  → generated skill list

Both resolve
  → normalise to unified item shape
  → derive tags for each item
  → merge into single sorted list (tools first, skills appended)
  → derive unique tag set for filter bar

User interacts with filter bar
  → selectedTags: Set<string>
  → andMode: boolean
  → visible = filter(items, selectedTags, andMode)
  → ToolCard list re-renders
```

## Category Badge Colours

`ToolCard` uses `CATEGORY_COLOR[tool.category]` for the category badge. The existing map covers built-in tool categories only (`swarm`, `kafka`, `orchestration`, `elastic`, `network`). Skill-derived categories must be added so they don't all render as grey:

```js
const CATEGORY_COLOR = {
  // existing built-in tool categories
  swarm:         'bg-blue-900 text-blue-300',
  kafka:         'bg-purple-900 text-purple-300',
  orchestration: 'bg-amber-900 text-amber-300',
  elastic:       'bg-teal-900 text-teal-300',
  network:       'bg-green-900 text-green-300',
  // skill categories
  compute:       'bg-sky-900 text-sky-300',
  monitoring:    'bg-cyan-900 text-cyan-300',
  storage:       'bg-violet-900 text-violet-300',
  general:       'bg-slate-700 text-slate-300',
  // common service names (auto-generated skills)
  proxmox:       'bg-orange-900 text-orange-300',
  fortigate:     'bg-red-900 text-red-300',
  truenas:       'bg-indigo-900 text-indigo-300',
  docker:        'bg-blue-900 text-blue-300',
}
// Fallback for unknown tags: 'bg-slate-700 text-slate-300'
```

## Skill Param Normalisation

`/api/skills` returns params as a JSON Schema object:
```js
parameters: {
  type: "object",
  properties: { node: { type: "string", description: "…" } },
  required: ["node"]
}
```

`/api/tools` returns params as a flat array:
```js
params: [{ name: "node", type: "string", required: true, description: "…" }]
```

Skills must be normalised to the flat array shape before being passed to `ToolCard`. Normalisation function:

```js
function normaliseSkillParams(parameters) {
  const props = parameters?.properties ?? {}
  const required = parameters?.required ?? []
  return Object.entries(props).map(([name, schema]) => ({
    name,
    type:        schema.type ?? 'string',
    description: schema.description ?? '',
    required:    required.includes(name),
    default:     schema.default ?? '',
  }))
}
```

## Files Changed

| File | Change |
|------|--------|
| `gui/src/components/CommandPanel.jsx` | Fetch + merge skills, normalise params, tag derivation, multi-select tag filter bar, AND/OR toggle, `source`-aware invoke in `ToolCard`, `generated` badge |
| `gui/src/api.js` | No change — `fetchSkills()` already exists |

## Out of Scope

- Editing skills from the Commands tab (Skills tab only)
- Persisting tag filter state across page reloads
- Backend changes of any kind
- Removing the Skills tab

## Success Criteria

1. A newly created skill appears in the Commands tab on next refresh without any manual step.
2. If the skill has `compat.service = "proxmox"`, a "Proxmox" tag button appears automatically.
3. Selecting "Proxmox" + "Monitoring" in AND mode shows only items tagged with both.
4. Selecting "Proxmox" + "Monitoring" in OR mode shows all Proxmox items and all Monitoring items.
5. Generated skills show an amber `generated` badge.
6. Invoking a skill from Commands works identically to invoking it from the Skills tab.
7. The Skills tab is visually and functionally unchanged.
