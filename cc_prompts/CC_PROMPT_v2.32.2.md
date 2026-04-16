# CC PROMPT — v2.32.2 — Post-action verify step

## What this does
Adds automatic state verification after destructive tool calls succeed. When the execute
agent runs a destructive tool and gets `status: ok`, the harness automatically calls a
corresponding read-only verification tool to confirm the state actually changed. This
catches the "premature completion" failure mode where the action succeeds but the
infrastructure doesn't converge.

This is the **acceptance-gated attempt loop** from the harness engineering research —
the only module that consistently improved performance in ablation studies.

Version bump: 2.32.1 → 2.32.2

## Change 1 — api/routers/agent.py — Add verify map and function

Add this new dict and function AFTER the `DESTRUCTIVE_TOOLS` frozenset definition and
BEFORE the `_AGENT_MAX_WALL_CLOCK_S` line:

```python
# ─── Post-action verification map (v2.32.2) ──────────────────────────────────
# Maps destructive tool → (verify_tool_name, args_builder_function)
# args_builder receives the original tool's fn_args and returns verify tool args.
# Only tools where state verification is meaningful are included.

def _verify_spec(tool_name: str, fn_args: dict) -> tuple[str, dict] | None:
    """Return (verify_tool, verify_args) for a destructive tool, or None if no verify needed."""
    if tool_name == "swarm_service_force_update":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("service_health", {"service_name": svc})
    elif tool_name == "proxmox_vm_power":
        # After rebooting a VM, check if Swarm nodes recovered
        return ("swarm_node_status", {})
    elif tool_name == "service_upgrade":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("post_upgrade_verify", {"service_name": svc})
    elif tool_name == "service_rollback":
        svc = fn_args.get("service_name", "")
        if svc:
            return ("service_health", {"service_name": svc})
    elif tool_name == "node_drain":
        return ("swarm_node_status", {})
    elif tool_name == "node_activate":
        return ("swarm_node_status", {})
    # docker_prune already returns before/after data — no separate verify needed
    # skill tools don't need infra verification
    return None


async def _auto_verify(
    tool_name: str,
    fn_args: dict,
    session_id: str,
    operation_id: str,
) -> dict | None:
    """Run post-action verification. Returns verify result dict or None if skipped.

    Called by the agent loop after a destructive tool returns status=ok.
    The verification is harness-driven — the model doesn't decide to verify,
    the harness does it automatically.
    """
    spec = _verify_spec(tool_name, fn_args)
    if spec is None:
        return None

    verify_name, verify_args = spec

    await manager.send_line(
        "step",
        f"[verify] Auto-verifying via {verify_name}...",
        status="ok", session_id=session_id,
    )

    try:
        verify_result = await asyncio.get_event_loop().run_in_executor(
            None, lambda vn=verify_name, va=verify_args: invoke_tool(vn, va)
        )
    except Exception as e:
        log.debug("Auto-verify %s failed: %s", verify_name, e)
        await manager.send_line(
            "step",
            f"[verify] {verify_name} failed: {str(e)[:100]}",
            status="warning", session_id=session_id,
        )
        return None

    v_status = verify_result.get("status", "error") if isinstance(verify_result, dict) else "error"
    v_message = verify_result.get("message", "") if isinstance(verify_result, dict) else str(verify_result)

    # Log the verify call
    await logger_mod.log_tool_call(
        operation_id, verify_name, verify_args, verify_result,
        _lm_model(), 0, status="ok",
    )

    # Determine if verification passed
    passed = v_status in ("ok", "healthy")
    icon = "✓" if passed else "⚠"

    await manager.send_line(
        "step",
        f"[verify] {icon} {verify_name} → {v_status} | {v_message[:120]}",
        tool=verify_name, status="ok" if passed else "warning",
        session_id=session_id,
    )

    return {
        "verify_tool": verify_name,
        "verify_status": v_status,
        "verify_message": v_message[:200],
        "passed": passed,
    }
```

## Change 2 — api/routers/agent.py — Wire verify into the tool execution loop

In the `_run_single_agent_step` function, find the block that handles destructive tool
call counting. It currently looks like this (after the `invoke_tool` call):

```python
                        if fn_name in DESTRUCTIVE_TOOLS:
                            _destructive_calls += 1
```

Replace that block with:

```python
                        if fn_name in DESTRUCTIVE_TOOLS:
                            _destructive_calls += 1
                            # v2.32.2: Auto-verify after successful destructive action
                            if result_status == "ok" or (isinstance(result, dict) and result.get("data", {}).get("approved")):
                                _vr = await _auto_verify(fn_name, fn_args, session_id, operation_id)
                                if _vr and not _vr["passed"]:
                                    # Verification failed — inject warning into model context
                                    _verify_warning = (
                                        f"[HARNESS VERIFY WARNING] After {fn_name} returned ok, "
                                        f"auto-verification via {_vr['verify_tool']} returned "
                                        f"{_vr['verify_status']}: {_vr['verify_message']}. "
                                        f"The action may not have taken effect yet."
                                    )
                                    # Don't append as separate message — will be included
                                    # in the tool result content below
                                    tool_content_suffix = f"\n\n{_verify_warning}"
                                elif _vr and _vr["passed"]:
                                    tool_content_suffix = (
                                        f"\n\n[HARNESS VERIFY OK] {_vr['verify_tool']} confirmed: "
                                        f"{_vr['verify_status']}"
                                    )
                                else:
                                    tool_content_suffix = ""
```

IMPORTANT: You also need to initialize `tool_content_suffix = ""` at the start of each
tool call iteration (right after `fn_name = tc.function.name`), and append it to the
tool content when building the message. Find the line:

```python
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_content,
                })
```

And change it to:

```python
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_content + tool_content_suffix,
                })
```

Make sure `tool_content_suffix` is initialized to `""` early in the tool call loop
(after `fn_name = tc.function.name`) so it's always defined, even for non-destructive tools.

## Change 3 — Handle the result_status timing

There's a subtle ordering issue: `result_status` is computed AFTER the tool execution,
but the verify block references it. The current code has:

```python
                result_status = result.get("status", "error") if isinstance(result, dict) else "error"
```

This line must come BEFORE the destructive tool verify block. Check that the ordering is:
1. `result = await ... invoke_tool(...)` (or the plan_action/escalate/clarify special cases)
2. `result_status = result.get("status", "error") ...`
3. `if fn_name in DESTRUCTIVE_TOOLS:` (the verify block)
4. Duration, logging, streaming
5. `messages.append(...)` with `tool_content + tool_content_suffix`

If `result_status` is currently computed after the destructive check, move it before.
Looking at the existing code, `result_status` is computed at:
```python
                result_status = result.get("status", "error") if isinstance(result, dict) else "error"
                result_msg = result.get("message", "") if isinstance(result, dict) else str(result)
```
which appears AFTER `_destructive_calls += 1`. Move the `result_status` and `result_msg`
assignment to BEFORE the destructive check block. The duration_ms line can stay where it is.

## Version bump

Update VERSION file: 2.32.1 → 2.32.2

## Commit

```bash
git add -A
git commit -m "feat(agents): v2.32.2 post-action verify step

After a destructive tool returns status=ok, the harness automatically
calls a read-only verification tool to confirm the state changed:
- swarm_service_force_update → service_health
- proxmox_vm_power → swarm_node_status
- service_upgrade → post_upgrade_verify
- service_rollback → service_health
- node_drain/activate → swarm_node_status

Verification is harness-driven (not model-decided). Results are:
- Streamed to WebSocket as [verify] steps
- Appended to tool result so model sees pass/fail
- Logged to operation log for audit trail

Catches the 'premature completion' failure mode where the action
API returns success but infrastructure hasn't converged."
git push origin main
```
