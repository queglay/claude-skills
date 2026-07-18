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

## The shift

1. **Open the shift log.** Record the goal and a resume point (task list or
   a notes file) — the handover note. Confirm the meter reads cleanly here,
   before committing to the run — a `?`, a stale tee, or a reset already in
   the past means you would be flying blind, so fix the meter or hand back
   to the user rather than start an autonomous shift on a broken gauge.
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
   report the task's own instructions call for.

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
- The handover note is the single source of truth for resume state; trust
  it over memory of what you "were doing".
