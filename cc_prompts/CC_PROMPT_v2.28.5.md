# CC PROMPT — v2.28.5 — Fix build errors: cardSchemas JSX + Sidebar duplicate borderLeft

## What this does
Two build-breaking fixes from v2.28.0–v2.28.2:
1. `gui/src/schemas/cardSchemas.js` contained JSX (`<div>`, `<span>`) which Rollup cannot
   parse in a `.js` file. Fix: convert all JSX to `React.createElement()` calls in `.jsx` file,
   stub `.js` to re-export.
2. `gui/src/components/Sidebar.jsx` had a duplicate `borderLeft` key in the nav button style
   object (esbuild warning treated as error). Fix: remove the first occurrence.

Both files already fixed directly — this prompt only bumps the version and commits.
Version bump: 2.28.4 → 2.28.5

---

## Files already fixed (no code changes needed in this prompt)

- `gui/src/schemas/cardSchemas.jsx` — created with `React.createElement()` instead of JSX
- `gui/src/schemas/cardSchemas.js` — now just `export * from './cardSchemas.jsx'`
- `gui/src/components/Sidebar.jsx` — duplicate `borderLeft` removed

CC should verify these files exist and are correct, then proceed directly to version bump and commit.

---

## Version bump
Update VERSION: 2.28.4 → 2.28.5

## Commit
```bash
git add -A
git commit -m "fix(build): v2.28.5 cardSchemas JSX→createElement, Sidebar duplicate borderLeft"
git push origin main
```
