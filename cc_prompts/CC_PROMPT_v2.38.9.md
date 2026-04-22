# CC PROMPT — v2.38.9 — fix(ui): TOOLBOX CollapsibleSection wrong prop name (label → title)

## What this does

v2.38.8 wrapped the toolbox in `CollapsibleSection` but passed `label=` instead
of `title=`. The `CollapsibleSection` component only reads `title` — `label` is
silently ignored, leaving the header button blank (just a `›` chevron, no text).

One-line fix: rename the prop.

Version bump: 2.38.8 → 2.38.9.

---

## Change 1 — `gui/src/components/CommandPanel.jsx`

Locate:

```jsx
        <CollapsibleSection
          storageKey="toolbox"
          defaultOpen={false}
          label={`TOOLBOX${items.length > 0 ? ` (${items.length})` : ''}`}
        >
```

Replace with:

```jsx
        <CollapsibleSection
          storageKey="toolbox"
          defaultOpen={false}
          title={`TOOLBOX${items.length > 0 ? ` (${items.length})` : ''}`}
        >
```

---

## Version bump

Update `VERSION` file: `2.38.8` → `2.38.9`

---

## Commit

```
git add -A
git commit -m "fix(ui): v2.38.9 TOOLBOX CollapsibleSection label → title prop"
git push origin main
```

Then deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
