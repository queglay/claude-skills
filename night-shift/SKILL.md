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

[`scripts/usage-check`](scripts/usage-check) prints one line:

    <five_hr%> <seven_day%> <five_hr_reset_iso> <seven_day_reset_iso>

It reads the Claude Code OAuth token from the macOS Keychain at runtime —
nothing is stored. Install once: copy to `~/.local/bin/usage-check` and
`chmod +x` it. A `?` in any field, or a reset timestamp in the past, means
the meter is broken: report that and ask the user rather than guess
headroom.

## The shift

1. **Open the shift log.** Record the goal and a resume point (task list or
   a notes file) — the handover note. Done when a fresh context could
   resume the work from the note alone.
2. **Meter every turn.** Run the meter after each unit of work. Under the
   wall — default 90% five-hour — keep working.
3. **Clock out ahead of the wall.** When the current reading plus the next
   atomic chunk would cross the wall, checkpoint now: commit and push
   what's in flight, bring the handover note current. Pausing a few percent
   early is cheap; getting cut mid-refactor is not. Done when the working
   tree is clean and the note says exactly where to pick up.
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

- The seven-day meter is the long fuse: past its own wall (default 80%),
  surface to the user and stop looping — sleeping recovers a five-hour
  window, never a weekly cap.
- One sleeper at a time: before scheduling a wake, confirm no earlier wake
  is already pending, so two shifts never overlap.
- The handover note is the single source of truth for resume state; trust
  it over memory of what you "were doing".
