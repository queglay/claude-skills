# Evals — the enforced meter gate

One deterministic, hermetic, free suite: `test_meter_gate.py`. No pooled score
(mirroring the `adversarial-thought` doctrine) — each test re-derives one
invariant of `scripts/meter-gate.py`, the PreToolUse hook that DENIES a fan-out
launch once the five-hour usage window is at/over the wall.

```
python3 evals/test_meter_gate.py            # verbose; non-zero exit on any failure
python3 -m unittest evals.test_meter_gate   # from the skill root
```

This tier **gates**: a red run means the enforced backstop is broken and must not
ship.

## What each group measures

| Group | Invariant | Why it matters |
|-------|-----------|----------------|
| **IncidentReplay** | armed shift + meter past wall + a background build → **denied** | The one regression guard for the real failure: a run drove five-hour to 100% by launching unmetered blind stretches. If nothing else, this must stay green. |
| **Behavioral** | no-marker→allow; under-wall→allow; ≥wall→block; foreground Bash never gated; Agent/Task/Workflow/background-Bash gated; wall read from the marker; `?` reset field never parsed as the percent | The gate's scope and the inclusive `>= wall` boundary. |
| **FailOpen** | non-numeric / empty / `? ? ? ?` / non-finite reading → **allow**; unparseable, empty, or out-of-range (`>100`, negative) marker wall → default 90; a fractional reading is floored, not dropped | A broken gauge must never brick the user's tools, and a malformed wall must fail toward protection (90), never silently disable the gate. The only block path is a clean numeric percent ≥ wall. |
| **Concurrency** | disarm one shift leaves the other protected; last disarm makes the gate inert; the **minimum** wall across shifts applies **and an empty/default marker pulls that min down to 90** (never dropped); the gate is **session-agnostic** | The multi-session correctness this rewrite exists for — see below. |
| **KnownGaps** | a foreground self-detach (`claude -p … &`) is **not** gated — pinned, not fixed | Documents an accepted limitation so a scope change can't silently widen it. Green here means "still exactly this gap," not "safe." |
| **LegacyMigration** | a live global `~/.claude/night-shift-active` still gates, with its wall, and surfaces a deprecation note | Migration fails LOUD, never silently unprotects someone who armed the old way. |
| **Hermeticity** | with a reading injected the gate NEVER executes `usage-check` (a canary sentinel proves it), and a control shows it DOES shell out with no injection | Behavioral proof — not a source-string match — that the suite never hits the network or the OAuth credential. |

## The contract each test actually exercises

Every test invokes `meter-gate.py` **as a subprocess** with a real stdin JSON
payload and asserts on its **exit code** (`0` allow / `2` block) — the true hook
contract, not a function return. A test that imported the function and checked a
value would skip the stdin-parse and exit-code path that is the whole integration
surface.

Hermetic and free: each test runs against a throwaway tempdir marker directory
(`NIGHT_SHIFT_DIR`) and injects the meter reading (`NIGHT_SHIFT_TEST_READING`).
The real `usage-check` — which hits `api.anthropic.com` and reads the OAuth
credential — is **never** called. `NIGHT_SHIFT_SENTINEL` is repointed at a
guaranteed-absent path per test so the ambient real legacy file can't leak in.

## The concurrency rewrite this suite pins

The old gate used **one global sentinel file**. Disarming any shift removed it
and silently unprotected every other concurrent shift. The rewrite replaces it
with a **directory of per-session markers**: arm creates `<dir>/<session_id>`,
disarm removes only that one, and the gate blocks whenever **any** marker exists.

Reproduce-first proof (the `TestConcurrency` isolation test is a real regression
guard, not a vacuous pass): against the old global-sentinel gate, after shift A
disarms, a fan-out from still-active shift B at 95% returns exit `0` — B is
**unprotected**. Against the new gate the same scenario returns exit `2`.

Two design choices are load-bearing and deliberately tested:

- **Session-agnostic predicate ("block if any marker exists").** The gate never
  consults the payload's session id. This preserves **coverage**: a nested
  subagent or a Workflow whose hook payload may carry a *child* session id (the
  docs don't specify which id it carries) is still gated. A "block only my
  session" predicate would let those escape — narrowing the safety net while
  "fixing" it.
- **Minimum wall across active shifts.** The strictest wall wins, so no shift is
  ever under-protected by another's laxer setting.

The accepted cost: while any shift is active, an unrelated terminal near the wall
is also gated. Deliberate — the five-hour limit is account-global, so
over-protecting is the safe direction; under-protecting was the bug.

## What green does NOT establish (honest boundaries)

- **Green ≠ the real usage API is read correctly.** The suite injects the meter
  reading; it never exercises `usage-check`'s network call or its parse of the
  live OAuth-usage response. That the injected format matches what `usage-check`
  actually prints is an integration assumption, not a tested one.
- **Green ≠ Claude Code passes the payload we assume.** The tests feed the
  documented PreToolUse JSON shape. That the running Claude Code actually
  delivers `tool_name` / `tool_input` / `run_in_background` as modeled is
  verified against the docs, not re-proven here.
- **Green ≠ the wall is well-chosen.** Whether 90% is the right floor, or whether
  the 1/5-headroom cap (owned by SKILL.md per-turn discipline, not this gate) is
  respected, is a policy judgement no deterministic test can settle.
- **Green ≠ a single in-flight overshoot is caught.** The gate is a pre-launch
  FLOOR: it stops a NEW blind stretch from starting past the wall. It cannot
  interrupt one already-running fan-out that overshoots, and for a Workflow it
  gates the top-level launch, not the agents that Workflow spawns internally.
- **Green ≠ a self-detached foreground command is caught.** Foreground Bash is
  exempt by design (keyed on the `run_in_background` flag), so a `claude -p … &`
  or `nohup` fan-out escapes — a known, pinned gap (`TestKnownGaps`). Not gating
  it is deliberate: content-parsing would false-gate a clock-out commit whose
  message mentions "claude". The model must not self-detach a blind stretch.
- **Green ≠ the matcher covers every fan-out primitive.** Coverage is bounded by
  the `settings.json` PreToolUse matcher (`Agent|Task|Workflow|Bash`), which
  lives in the private config repo, not here. A future tool or an MCP server
  that spawns Claude work outside that matcher never invokes the gate.
