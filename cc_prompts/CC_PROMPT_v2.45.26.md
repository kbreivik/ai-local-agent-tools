# CC PROMPT — v2.45.26 — fix(settings): runbookInjectionMode default — align with implemented behaviour

## What this does
Tiny alignment fix from the v2.45.17 audit. The default for
`runbookInjectionMode` is `"augment"`, but `api/routers/agent.py` only
implements `"replace"` and silently falls back to `"replace"` for any other
value (with a TODO comment). The result: the documented default and the
actual runtime behaviour diverge — operators reading the setting see
"augment" but get "replace".

The cheapest fix is to change the registered default to `"replace"`. This
matches what actually runs. Implementing real `augment` mode is a separate,
larger change for a future v2.46.x cycle.

Version bump: 2.45.25 → 2.45.26

---

## Change 1 — `api/routers/settings.py` — change the default

CC: open `api/routers/settings.py`. Find the registration of
`runbookInjectionMode`. It will look something like:

```python
"runbookInjectionMode": {"default": "augment", ...}
```

or similar (the exact structure depends on whether it is in `SETTINGS_KEYS`,
a separate `DEFAULTS` dict, or a `seed_defaults()` body).

Change `"augment"` to `"replace"` everywhere `runbookInjectionMode` is
defaulted. There may be 1–3 occurrences. Update all of them.

---

## Change 2 — `gui/src/context/OptionsContext.jsx` — align frontend default

CC: open `gui/src/context/OptionsContext.jsx`. Find the `DEFAULTS` object
(or equivalent constants). Locate `runbookInjectionMode` if present. If its
value is `"augment"`, change to `"replace"`. If absent, add:

```javascript
runbookInjectionMode: 'replace',
```

Inside the DEFAULTS / SERVER_KEYS structure, in the section for Facts &
Knowledge or runbook settings — match the existing pattern.

---

## Change 3 — `api/routers/agent.py` — replace TODO with explicit comment

CC: open `api/routers/agent.py`. Search for `runbookInjectionMode` and the
falls-back-to-replace block. The status report references this site
(approximately line 724):

```python
# v2.36.3 only implements REPLACE. Other modes deferred to v2.36.5+.
if output_mode != "replace":
    # falls back to "replace" with a warning
```

Replace the comment block with:

```python
    # v2.45.26 — Default is "replace" (matches what is implemented). Other
    # modes ("augment", "replace+shrink") are accepted by settings validation
    # but treated as "replace" at runtime. Real "augment" semantics is a
    # planned v2.46.x change once a base-prompt + runbook-prepend strategy
    # has been designed.
```

Leave the actual control flow alone — the fall-through behaviour remains
correct given the new default.

---

## Verify

```bash
python -m py_compile api/routers/settings.py api/routers/agent.py
grep -n "runbookInjectionMode" api/routers/settings.py gui/src/context/OptionsContext.jsx | head -10
```

Expected: every defaulted occurrence of `runbookInjectionMode` shows
`"replace"`, not `"augment"`. Existing user-saved values in the DB are not
touched — only the seeded default for fresh installs / unset keys.

After deploy, on a fresh install:
- `GET /api/settings` should return `runbookInjectionMode: "replace"` when
  it has not been overridden.
- Existing operators with `"augment"` already saved will see no behaviour
  change — they were already getting `"replace"` semantics.

---

## Version bump

Update `VERSION`: `2.45.25` → `2.45.26`

---

## Commit

```
git add -A
git commit -m "fix(settings): v2.45.26 runbookInjectionMode default — align with implemented behaviour (replace)"
git push origin main
```

Deploy:
```
docker compose -f /opt/hp1-agent/docker/docker-compose.yml \
  --env-file /opt/hp1-agent/docker/.env up -d hp1_agent
```
