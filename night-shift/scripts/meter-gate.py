#!/usr/bin/env python3
"""Night-shift ENFORCED meter gate (PreToolUse).

Sentinel-gated: does nothing unless the shift sentinel exists, so normal
(non-night-shift) sessions pay one stat() and exit 0. During an active shift it
runs the usage meter before every fan-out launcher and DENIES (exit 2, the same
block signal trust-gate.sh uses) when the five-hour window is at/over the wall.

This is the enforced backstop to the skill's per-turn metering discipline — the
reason it exists: a run drove five-hour from under-wall to 100% by launching
UNMETERED blind stretches (a background build, nested subagents, a Workflow)
with no clock-out. Model discipline alone had zero enforcement.

Scope — what it gates (the blind-stretch launchers):
  Agent / Task / Workflow  -> always (each is a fan-out)
  Bash with run_in_background=true -> a detached build/`claude -p` is a fan-out
  Foreground Bash          -> NEVER gated (git/python/checks stay fast; a meter
                              hiccup can't brick the shift's ordinary commands)

It is a pre-launch FLOOR, not the whole wall: it stops a NEW blind stretch from
STARTING past the wall. It cannot interrupt a single in-flight fan-out that
overshoots, and (for Workflow) it gates the top-level launch, not the agents a
Workflow spawns internally. It does not enforce the 1/5-headroom cap. Per-turn
metering in SKILL.md still owns those.

Fail-open: ANY error (missing/failing meter, parse failure, timeout) -> exit 0.
A broken gate must never brick the user's tools. The only exit-2 path is a
clean numeric five-hour percentage >= wall.

Test overrides (never set in normal use):
  NIGHT_SHIFT_SENTINEL      path to the sentinel file (default ~/.claude/night-shift-active)
  NIGHT_SHIFT_TEST_READING  fake meter output ("<pct> ..." or a non-numeric token)
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
SENTINEL = os.environ.get(
    "NIGHT_SHIFT_SENTINEL", os.path.join(HOME, ".claude", "night-shift-active"))
USAGE_CHECK = os.path.join(
    HOME, ".claude", "skills", "night-shift", "scripts", "usage-check")
DEFAULT_WALL = 90


def _five_hour_pct():
    """Five-hour usage percent as int, or None if unreadable/non-numeric.

    Only the FIRST field (the percentage) is parsed. usage-check prints
    '<five_hr%> <seven_day%> <five_hr_reset> <seven_day_reset>'; the reset field
    is a literal '?' at 0% right after a reset, so it must never influence the
    block decision. Non-numeric percentage -> None -> fail-open (not a block)."""
    inj = os.environ.get("NIGHT_SHIFT_TEST_READING")
    out = inj if inj is not None else subprocess.run(
        [USAGE_CHECK], capture_output=True, text=True, timeout=20).stdout
    fields = out.split()
    if not fields:
        return None
    try:
        return int(fields[0])
    except ValueError:
        return None


def main():
    # Sentinel gate: normal sessions leave here.
    if not os.path.exists(SENTINEL):
        return 0

    # Read the PreToolUse payload to see which tool is launching.
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}
    tool = payload.get("tool_name", "")
    tin = payload.get("tool_input") or {}

    # Foreground Bash is not a blind stretch — never gate it.
    if tool == "Bash" and not tin.get("run_in_background"):
        return 0

    # Wall lives in the sentinel (first token, int percent); default 90.
    wall = DEFAULT_WALL
    try:
        txt = open(SENTINEL).read().strip()
        if txt:
            wall = int(txt.split()[0])
    except Exception:
        wall = DEFAULT_WALL

    try:
        pct = _five_hour_pct()
    except Exception:
        return 0  # fail-open: meter unreadable -> allow (SKILL.md discipline stops)

    if pct is None:
        return 0  # broken gauge -> fail-open; the model clocks out, the gate doesn't brick
    if pct >= wall:
        sys.stderr.write(
            f"night-shift WALL: five-hour usage at {pct}% (wall {wall}%). "
            "Do NOT launch this fan-out. Clock out now: checkpoint the handover "
            "note, then sleep to the five-hour reset and clock back in.\n")
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # absolute fail-open backstop
