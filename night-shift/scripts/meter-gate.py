#!/usr/bin/env python3
"""Night-shift ENFORCED meter gate (PreToolUse).

Marker-gated: does nothing unless a shift marker exists, so normal
(non-night-shift) sessions pay one cheap dir listing and exit 0. During an
active shift it runs the usage meter before every fan-out launcher and DENIES
(exit 2, the same block signal trust-gate.sh uses) when the five-hour window is
at/over the wall.

This is the enforced backstop to the skill's per-turn metering discipline — the
reason it exists: a run drove five-hour from under-wall to 100% by launching
UNMETERED blind stretches (a background build, nested subagents, a Workflow)
with no clock-out. Model discipline alone had zero enforcement.

Concurrency model — why a marker DIRECTORY, not one global file:
  Each active shift owns a per-session marker file `<dir>/<session_id>` (arm
  creates it, disarm removes ONLY that one). The gate blocks whenever ANY marker
  exists — it is deliberately session-AGNOSTIC. That choice is load-bearing:
    * ISOLATION — one shift's disarm removes only its own marker, so it can
      never silently unprotect a concurrent shift (the old global `rm -f` bug).
    * COVERAGE — the gate is what catches nested subagents / a Workflow whose
      hook payload may carry a CHILD session id, not the arming session's. A
      "block only MY session" predicate would let those escape; "block if any
      marker exists" cannot regress that coverage.
  The accepted cost: while any shift is active, an UNRELATED terminal near the
  wall is also gated. Deliberate — the five-hour limit is account-global, so
  over-protecting is the safe direction; under-protecting is the bug we fixed.
  The wall applied is the MOST CONSERVATIVE (minimum) across all active markers,
  so no shift is ever under-protected by another's laxer wall.

Legacy migration (fail LOUD, never silent): a pre-existing global
`~/.claude/night-shift-active` from the old single-file design is still honored
as a marker (predicate + wall), so anyone who armed the old way stays protected.
A deprecation note is appended to the block message when a legacy file is seen.

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
  NIGHT_SHIFT_DIR           marker directory (default ~/.claude/night-shift)
  NIGHT_SHIFT_SENTINEL      legacy global marker (default ~/.claude/night-shift-active)
  NIGHT_SHIFT_TEST_READING  fake meter output ("<pct> ..." or a non-numeric token)
"""
import json
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
MARKER_DIR = os.environ.get(
    "NIGHT_SHIFT_DIR", os.path.join(HOME, ".claude", "night-shift"))
LEGACY_SENTINEL = os.environ.get(
    "NIGHT_SHIFT_SENTINEL", os.path.join(HOME, ".claude", "night-shift-active"))
USAGE_CHECK = os.path.join(
    HOME, ".claude", "skills", "night-shift", "scripts", "usage-check")
DEFAULT_WALL = 90


def _active_marker_paths():
    """Every file that marks an active shift: per-session markers + legacy file.

    Returns a list of (path, is_legacy) for each existing marker. An empty list
    means no shift is active anywhere -> the gate does nothing."""
    paths = []
    try:
        for name in os.listdir(MARKER_DIR):
            p = os.path.join(MARKER_DIR, name)
            if os.path.isfile(p):
                paths.append((p, False))
    except (FileNotFoundError, NotADirectoryError):
        pass  # no marker dir yet -> no per-session shifts (legacy still checked)
    except Exception:
        # DELIBERATE fail-open on an unreadable marker dir (e.g. PermissionError
        # mid-shift): treat as no per-session markers so a broken FS can't brick
        # the user's tools. This is the ONE place the gate can under-protect an
        # armed shift; the model's own per-turn metering (SKILL.md) is the
        # primary wall and still stands. Narrow enough that a real bug surfaces.
        pass
    if os.path.exists(LEGACY_SENTINEL):
        paths.append((LEGACY_SENTINEL, True))
    return paths


def _wall_from(path):
    """First token of a marker file as an int percent in [0,100], else None.

    None (unreadable / non-numeric / out-of-range) makes the caller default the
    wall to DEFAULT_WALL (90). Out-of-range is treated as garbage on purpose: a
    parseable wall like 150 would otherwise silently DISABLE the gate (nothing
    ever reaches 150%), so a malformed marker must fail toward protection, not
    away from it."""
    try:
        txt = open(path).read().strip()
        if txt:
            w = int(txt.split()[0])
            return w if 0 <= w <= 100 else None
    except Exception:
        return None
    return None


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
        return int(float(fields[0]))  # tolerate "95.5" too; int() alone rejects it
    except (ValueError, OverflowError):
        return None  # non-numeric / inf / nan -> fail-open (broken gauge, not a block)


def main():
    # Marker gate: no active shift anywhere -> normal sessions leave here.
    markers = _active_marker_paths()
    if not markers:
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

    # Most conservative wall across all active shifts (min); an unparseable or
    # empty marker contributes DEFAULT_WALL (90) to the min, never nothing —
    # dropping it would silently raise the effective wall and under-protect the
    # shift that armed at default. `markers` is non-empty here, so `walls` is too.
    walls = [w if w is not None else DEFAULT_WALL
             for w in (_wall_from(p) for p, _ in markers)]
    wall = min(walls)
    has_legacy = any(is_legacy for _, is_legacy in markers)

    try:
        pct = _five_hour_pct()
    except Exception:
        return 0  # fail-open: meter unreadable -> allow (SKILL.md discipline stops)

    if pct is None:
        return 0  # broken gauge -> fail-open; the model clocks out, the gate doesn't brick
    if pct >= wall:
        msg = (
            f"night-shift WALL: five-hour usage at {pct}% (wall {wall}%). "
            "Do NOT launch this fan-out. Clock out now: checkpoint the handover "
            "note, then sleep to the five-hour reset and clock back in.\n")
        if has_legacy:
            msg += (
                "note: a legacy global ~/.claude/night-shift-active is still "
                "armed (deprecated single-file marker). Re-arm with the current "
                "per-session command and remove the legacy file once no shift "
                "relies on it.\n")
        sys.stderr.write(msg)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # absolute fail-open backstop
