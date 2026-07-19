---
name: night-shift
description: Work a long autonomous task across Claude usage windows — meter every turn, clock out before the wall, sleep to the reset, clock in and continue.
disable-model-invocation: true
---

Work the task like a shift worker covering nights: the shift ends when the
task is done, not when the usage window closes. Meter your burn, clock out
at a clean checkpoint before you hit the wall, sleep until the window
resets, clock in and pick up from your own handover note.

## The meter

Two ways to read the meters, in preference order:

1. **Statusline tee (no secrets, any platform).** Claude Code feeds its
   statusline script a JSON payload on stdin that already contains
   `rate_limits.five_hour.used_percentage`,
   `rate_limits.seven_day.used_percentage`, and their `resets_at` epochs
   (see the statusline docs' JSON schema). Configure a statusline script
   that tees that payload to a file (e.g.
   `~/.claude/statusline-latest.json`) and read the file each turn. No
   credential is touched; works wherever Claude Code runs. Limitation:
   the file only updates while a session is active, so check its mtime —
   a stale file is a broken meter, not a low reading.
2. **OAuth endpoint fallback.**
   [`scripts/usage-check`](scripts/usage-check) prints one line:

       <five_hr%> <seven_day%> <five_hr_reset_iso> <seven_day_reset_iso>

   It reads Claude Code's own OAuth token at runtime from wherever the
   platform stores it — macOS Keychain, else
   `$CLAUDE_CONFIG_DIR/.credentials.json` (`~/.claude` on
   Linux/containers). Nothing new is stored and no user-managed secret is
   required. Install once: copy to `~/.local/bin/usage-check` and
   `chmod +x` it.

Either way: a `?` or missing field, or a reset timestamp in the past,
means the meter is broken — report that and ask the user rather than
guess headroom.

## The enforced gate (backstop to step 2)

Metering every turn is *discipline*, and discipline alone once failed: a
run launched unmetered blind stretches — a background build, nested
subagents, a workflow — and drove five-hour from under-wall to 100% with
no clock-out. So the wall is also enforced in code.

[`scripts/meter-gate.py`](scripts/meter-gate.py) is a `PreToolUse` hook
(registered in `settings.json` for `Agent|Task|Workflow|Bash`). It is
**marker-gated**: it does nothing unless a shift marker exists in the marker
directory `~/.claude/night-shift/`, so normal sessions are unaffected. While
a shift is open it reads the five-hour meter before every fan-out launcher —
`Agent`/`Task`/`Workflow`, and `Bash` only when `run_in_background` is true —
and **denies the launch (exit 2)** when the clean five-hour percentage is at
or over the wall (the most conservative wall across active markers, read from
each marker's first line, default 90).

**Multi-session safe.** Each shift owns a per-session marker
`~/.claude/night-shift/<session-id>`; arm creates *your* marker, disarm
removes *only* yours, and the gate blocks whenever *any* marker exists. So one
shift's clock-out can never silently unprotect a concurrent shift (the old
single global-file design could), and the gate stays session-agnostic on
purpose — a nested subagent or workflow whose hook payload may carry a *child*
session id is still gated, preserving coverage. The accepted trade: while any
shift is active, an unrelated terminal near the wall is also gated — the safe
direction, since the five-hour limit is account-global. A pre-existing legacy
global `~/.claude/night-shift-active` is still honored (with a deprecation
note) so an old-style arm stays protected. `evals/test_meter_gate.py` pins all
of this deterministically and hermetically; see [`evals/README.md`](evals/README.md).

It is a pre-launch **floor, not the whole wall**, and does not replace
step 2:
- It stops a *new* blind stretch from *starting* past the wall. It cannot
  interrupt a single in-flight fan-out that overshoots, and for a workflow
  it gates the top-level launch, not the agents the workflow spawns
  internally.
- It does **not** enforce the ⅕-headroom cap — that stays your job in
  step 2. The gate only catches the gross "already at the wall" case.
- Foreground `Bash` is never gated (git, checks, edits stay fast). **Known
  bypass — do not use it to evade the wall:** because the exemption keys off
  the `run_in_background` flag, a foreground `Bash` that *self-detaches* a
  fan-out (`claude -p … &`, `nohup`, a blocking `claude -p`, `xargs -P`) slips
  past the gate. Content-parsing the command was rejected on purpose — it would
  false-gate a clock-out `git commit -m "…claude…"` at the wall. So this stays
  the model's responsibility: never launch a blind stretch as a self-detached
  foreground command. `evals/test_meter_gate.py` pins this gap so a scope change
  can't widen it unnoticed.
- It **fails open**: any meter error → allow. A broken gate must never
  brick the session, so the model's own clock-out discipline remains the
  primary wall; the gate is the backstop.

## The shift

1. **Open the shift log.** Record the goal and a resume point (task list or
   a notes file) — the handover note. Confirm the meter reads cleanly here,
   before committing to the run — a `?`, a stale tee, or a reset already in
   the past means you would be flying blind, so fix the meter or hand back
   to the user rather than start an autonomous shift on a broken gauge.
   Then **arm the enforced gate**: write *your* per-session marker with the
   wall percent so the backstop is live for the whole shift —

       mkdir -p ~/.claude/night-shift
       printf '90\n' > ~/.claude/night-shift/"$CLAUDE_CODE_SESSION_ID"

   The marker is keyed to this session, so a concurrent shift in another
   terminal is untouched. (If `$CLAUDE_CODE_SESSION_ID` is ever empty, pick any
   stable unique token and reuse the *same* one at disarm.)
   Done when a fresh context could resume the work from the note alone.
2. **Meter every turn.** Run the meter after each unit of work. Under the
   wall — default 90% five-hour — keep working. **A batch counts as one
   chunk.** A turn that fans out nested Claude work — a background
   `claude -p` sweep, a workflow, parallel subagents — burns *between*
   meter reads, in a **blind stretch**, by an amount you cannot reliably
   predict: an innocuous-looking run may itself spawn more Claude, so a raw
   count of invocations is not a cost. Do not trust a prediction — bound
   the blind stretch so a wrong guess cannot breach:
   - **Cap it.** Never launch a fan-out whose projected burn exceeds a
     small fraction of your *remaining* headroom to the wall — default **a
     fifth of what is left**. Then a batch that costs several times its
     estimate still lands short of the wall.
   - **Or split it.** If it will not fit under the cap, break it into
     smaller batches with a meter read between each — one blind stretch
     becomes several metered ones, restoring the reactive wall's sight.
   - **Measure, don't guess.** To run a batch too big to split, first
     launch the smallest useful slice, meter the delta, and size the rest
     from that *measured* per-unit cost.
   Re-meter the moment a batch returns — read the meter on the near side
   of a long stretch, not only the far side.
3. **Clock out ahead of the wall.** When the current reading plus the next
   atomic chunk — a batch counted whole — would cross the wall, checkpoint
   now: commit and push what's in flight, bring the handover note current.
   Pausing a few percent early is cheap; getting cut mid-refactor is not.
   Done when the working tree is clean and the note says exactly where to
   pick up.
4. **Sleep to the reset.** Schedule the wake with a background shell
   command that sleeps until `five_hr_reset` plus a 30s margin — its
   completion re-invokes you. BSD/macOS date arithmetic:

       now=$(date -u +%s)
       target=$(date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "<five_hr_reset>" +%s)
       sleep $((target + 30 - now))

   Then end the turn, telling the user the run is paused and when it
   resumes.
5. **Clock in.** On wake, run the meter to confirm the window reset, read
   the handover note, and return to step 2.
6. **Close the shift** when the task itself is complete, with whatever
   report the task's own instructions call for. **Disarm the gate** —
   remove *your* marker so it stops metering this session's ordinary future
   work (any concurrent shift keeps its own marker and stays protected):

       rm -f ~/.claude/night-shift/"$CLAUDE_CODE_SESSION_ID"

## Guardrails

- **The reactive wall: a usage-limit error is a breach, not a retry.** The
  meter in step 2 is the *predictive* wall — it clocks you out before the
  burn lands. This is the backstop for when a burst outruns it. If any
  operation comes back with a usage-limit / 429 / "session limit" /
  "usage limit" error — a main turn, a subagent, or a nested `claude -p`
  inside a batch — the wall is already crossed. Clock out immediately:
  stop launching work, do **not** retry the failed call or let the batch
  keep firing, checkpoint the handover note, and sleep to the reset named
  in the error (or the meter). A limit error is proof, not noise — never
  book a "you've hit your session limit" reply as a result, and treat any
  tool that invokes Claude on your behalf as required to surface that
  error, not swallow it as data. A batch that returns limit errors
  produced no data — discard it and resume it after the reset, do not
  read its output as findings.
- The seven-day meter is the long fuse, with its **own wall — default
  90%**. This is a separate knob from the five-hour wall in step 2; the
  two defaults happen to share the value 90% but govern different
  windows and different responses. Past the five-hour wall you sleep to
  the reset; past the seven-day wall you surface to the user and stop
  looping — sleeping recovers a five-hour window, never a weekly cap.
- One sleeper at a time: before scheduling a wake, confirm no earlier wake
  is already pending, so two shifts never overlap.
- A **stale marker** (a shift that crashed without reaching step 6) only
  ever *over*-protects — it meters a normal session and, near the wall,
  blocks a fan-out that discipline would have caught anyway. It never
  destroys work. If an ordinary session is unexpectedly gated, clear your
  own with `rm -f ~/.claude/night-shift/"$CLAUDE_CODE_SESSION_ID"`, or list
  `~/.claude/night-shift/` and remove the crashed session's marker by name.
  (A stale legacy `~/.claude/night-shift-active` clears with `rm -f` on that
  path — the gate names it in its deprecation note.)
- The handover note is the single source of truth for resume state; trust
  it over memory of what you "were doing".
