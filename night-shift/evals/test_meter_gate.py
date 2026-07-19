#!/usr/bin/env python3
"""Deterministic, hermetic evals for meter-gate.py — the enforced night-shift wall.

Doctrine (mirrors the sibling pr-review-video evals): no pooled score, each test
re-derives one invariant, and every test asserts the REAL integration contract —
the gate is invoked as a SUBPROCESS with a real stdin JSON payload and the assert
is on its EXIT CODE (0 allow / 2 block). Importing a function and checking a
return value would skip the stdin-parse and exit-code path that IS the whole hook
surface, so we never do that.

Hermetic and free: every test runs against a throwaway tempdir marker directory
and injects the meter reading via NIGHT_SHIFT_TEST_READING. The real usage-check
(network + OAuth credential) is NEVER called — test_hermetic_no_network_no_creds
asserts that structurally.

Run:  python3 evals/test_meter_gate.py            # verbose
      python3 -m unittest evals.test_meter_gate   # from the skill root
Exit non-zero on any failure — this is a gate.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = os.path.join(HERE, "..", "scripts", "meter-gate.py")


def run_gate(payload, *, marker_dir, reading=None, legacy=None, extra_env=None):
    """Invoke meter-gate.py as the hook harness does. Returns (rc, stderr).

    payload   dict -> serialized to stdin as the PreToolUse JSON.
    reading   str  -> NIGHT_SHIFT_TEST_READING (fake meter). None = unset.
    legacy    str  -> NIGHT_SHIFT_SENTINEL (legacy global path). None = a path
                      inside the tempdir that does not exist (so it is inert).
    """
    env = dict(os.environ)
    env["NIGHT_SHIFT_DIR"] = marker_dir
    # Point the legacy sentinel at a guaranteed-absent path unless a test sets one,
    # so the ambient real ~/.claude/night-shift-active can never leak in.
    env["NIGHT_SHIFT_SENTINEL"] = legacy if legacy is not None else os.path.join(
        marker_dir, "__no_such_legacy__")
    if reading is not None:
        env["NIGHT_SHIFT_TEST_READING"] = reading
    else:
        env.pop("NIGHT_SHIFT_TEST_READING", None)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, GATE],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=30)
    return proc.returncode, proc.stderr


def marker(marker_dir, session_id, wall="90"):
    """Arm a per-session shift: write <marker_dir>/<session_id> with a wall."""
    os.makedirs(marker_dir, exist_ok=True)
    with open(os.path.join(marker_dir, session_id), "w") as f:
        f.write(wall + "\n")


FANOUT = {"tool_name": "Agent", "tool_input": {"description": "x"}}
FG_BASH = {"tool_name": "Bash", "tool_input": {"command": "git status"}}
BG_BASH = {"tool_name": "Bash",
           "tool_input": {"command": "python build.py", "run_in_background": True}}


class GateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self._tmp.name, "night-shift")

    def tearDown(self):
        self._tmp.cleanup()


class TestIncidentReplay(GateBase):
    """The single highest-value eval: replay the failure the gate exists to stop."""

    def test_armed_shift_past_wall_denies_background_build(self):
        # A shift is armed; five-hour has climbed past the wall; a background
        # build is launched — exactly the unmetered blind stretch that drove
        # usage to 100%. It MUST be denied.
        marker(self.dir, "sessA", wall="90")
        rc, err = run_gate(BG_BASH, marker_dir=self.dir, reading="95 40 ? ?")
        self.assertEqual(rc, 2, "past-wall background build must be blocked")
        self.assertIn("WALL", err)
        self.assertIn("95%", err)


class TestBehavioral(GateBase):
    def test_no_marker_allows(self):
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="99 40 ? ?")
        self.assertEqual(rc, 0, "no active shift -> gate is inert even at 99%")

    def test_under_wall_allows(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="80 40 ? ?")
        self.assertEqual(rc, 0)

    def test_at_wall_denies(self):
        marker(self.dir, "s", wall="90")
        rc, err = run_gate(FANOUT, marker_dir=self.dir, reading="90 40 ? ?")
        self.assertEqual(rc, 2, ">= wall is a block (boundary is inclusive)")
        self.assertIn("90%", err)

    def test_over_wall_denies(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="97 40 ? ?")
        self.assertEqual(rc, 2)

    def test_foreground_bash_never_gated(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FG_BASH, marker_dir=self.dir, reading="99 40 ? ?")
        self.assertEqual(rc, 0, "ordinary foreground commands must never brick")

    def test_background_bash_gated(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(BG_BASH, marker_dir=self.dir, reading="99 40 ? ?")
        self.assertEqual(rc, 2)

    def test_task_and_workflow_gated(self):
        marker(self.dir, "s", wall="90")
        for tool in ("Task", "Workflow", "Agent"):
            rc, _ = run_gate({"tool_name": tool, "tool_input": {}},
                             marker_dir=self.dir, reading="99 40 ? ?")
            self.assertEqual(rc, 2, f"{tool} is a fan-out -> gated")

    def test_wall_read_from_marker(self):
        # A stricter wall in the marker (80) blocks a reading (85) that the
        # default wall (90) would allow — proves the wall comes from the file.
        marker(self.dir, "s", wall="80")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="85 40 ? ?")
        self.assertEqual(rc, 2)

    def test_reset_field_never_blocks(self):
        # The '?' reset token in field 3 must never be parsed as the percent.
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="10 40 ? ?")
        self.assertEqual(rc, 0, "only field[0] is the percent; '?' is ignored")


class TestFailOpen(GateBase):
    """A broken gauge must ALLOW (exit 0) — a broken gate must never brick tools."""

    def test_nonnumeric_reading_fails_open(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="unavailable")
        self.assertEqual(rc, 0)

    def test_empty_reading_fails_open(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="")
        self.assertEqual(rc, 0)

    def test_question_only_reading_fails_open(self):
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="? ? ? ?")
        self.assertEqual(rc, 0)

    def test_unparseable_marker_wall_defaults_90(self):
        # A garbage wall in the marker falls back to DEFAULT_WALL=90, still armed.
        marker(self.dir, "s", wall="garbage")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="92 40 ? ?")
        self.assertEqual(rc, 2, "unparseable wall -> default 90 -> 92 blocks")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="85 40 ? ?")
        self.assertEqual(rc, 0, "unparseable wall -> default 90 -> 85 allows")

    def test_empty_marker_file_defaults_90(self):
        os.makedirs(self.dir, exist_ok=True)
        open(os.path.join(self.dir, "s"), "w").close()  # zero-length marker
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="95 40 ? ?")
        self.assertEqual(rc, 2, "empty marker is still armed; default wall 90")

    def test_out_of_range_wall_defaults_90(self):
        # A parseable but impossible wall (>100) must be treated as garbage and
        # default to 90 — NOT honored literally. Honoring 150 would silently
        # DISABLE the gate (nothing reaches 150%), failing away from protection.
        marker(self.dir, "s", wall="150")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="92 40 ? ?")
        self.assertEqual(rc, 2, "wall 150 is garbage -> default 90 -> 92 blocks")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="85 40 ? ?")
        self.assertEqual(rc, 0, "wall 150 -> default 90 -> 85 allows")

    def test_negative_wall_defaults_90(self):
        # A negative wall is also out of range -> default 90 (not always-block).
        marker(self.dir, "s", wall="-5")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="85 40 ? ?")
        self.assertEqual(rc, 0, "wall -5 is garbage -> default 90 -> 85 allows")

    def test_fractional_reading_is_floored_not_dropped(self):
        # A fractional meter reading ("95.5") must parse to 95 and still block,
        # not ValueError into fail-open. (usage-check emits ints, so this is
        # defense-in-depth for a contract change, not a live path.)
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="95.5 40 ? ?")
        self.assertEqual(rc, 2, "95.5 -> int 95 >= 90 -> block")

    def test_infinite_reading_fails_open(self):
        # A non-finite reading must not crash int(float()) into a non-0/2 exit.
        marker(self.dir, "s", wall="90")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="inf 40 ? ?")
        self.assertEqual(rc, 0, "inf -> OverflowError caught -> fail-open allow")


class TestConcurrency(GateBase):
    """The bug this rewrite fixes: multiple shifts must not interfere.

    The old design used ONE global sentinel; disarming one shift removed it and
    silently unprotected every other. These tests pin the per-session-marker
    isolation and the coverage-preserving 'any marker' predicate.
    """

    def test_disarm_one_leaves_other_protected(self):
        # Two concurrent shifts. Remove A's marker (A disarms). B must STILL be
        # gated — the old global-rm bug would have unprotected B here.
        marker(self.dir, "sessA", wall="90")
        marker(self.dir, "sessB", wall="90")
        os.remove(os.path.join(self.dir, "sessA"))  # A clocks out
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="95 40 ? ?")
        self.assertEqual(rc, 2, "B's shift survives A's disarm (isolation)")

    def test_last_disarm_makes_gate_inert(self):
        marker(self.dir, "sessA", wall="90")
        marker(self.dir, "sessB", wall="90")
        os.remove(os.path.join(self.dir, "sessA"))
        os.remove(os.path.join(self.dir, "sessB"))
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="99 40 ? ?")
        self.assertEqual(rc, 0, "no markers left -> gate inert (no over-protection)")

    def test_min_wall_defaults_unparseable_marker(self):
        # An empty/default marker (wall -> 90) alongside a laxer parseable
        # marker (95) must pull the effective min wall down to 90, not be
        # dropped. Reading 92 is under 95 but over the empty marker's default
        # 90 -> must block. (Regression guard for the min-wall drop bug.)
        marker(self.dir, "sessLax", wall="95")
        os.makedirs(self.dir, exist_ok=True)
        open(os.path.join(self.dir, "sessDefault"), "w").close()  # empty -> 90
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="92 40 ? ?")
        self.assertEqual(
            rc, 2, "empty marker contributes default 90 to the min, not nothing")

    def test_min_wall_across_shifts(self):
        # A at wall 95, B at wall 80. A reading of 85 is under A's wall but over
        # B's — the most-conservative (min) wall must apply so B isn't
        # under-protected by A's laxer setting.
        marker(self.dir, "sessA", wall="95")
        marker(self.dir, "sessB", wall="80")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="85 40 ? ?")
        self.assertEqual(rc, 2, "min wall (80) applies across concurrent shifts")

    def test_coverage_is_session_agnostic(self):
        # The gate blocks whenever ANY marker exists, regardless of what session
        # id the payload carries. This is the COVERAGE property: a nested
        # subagent / Workflow whose payload may carry a child session id still
        # gets gated. A 'block only my session' predicate would let it escape.
        marker(self.dir, "the-arming-session", wall="90")
        payload = {"tool_name": "Workflow", "tool_input": {},
                   "session_id": "some-other-child-session"}
        rc, _ = run_gate(payload, marker_dir=self.dir, reading="95 40 ? ?")
        self.assertEqual(rc, 2, "any marker gates any session (coverage preserved)")


class TestKnownGaps(GateBase):
    """Documented, ACCEPTED limitations, pinned so a future change can't silently
    widen or narrow them unnoticed. Green here means 'still exactly this gap',
    not 'this is safe'. See SKILL.md 'Known bypass' + evals/README.md boundaries."""

    def test_foreground_self_detach_is_not_gated(self):
        # A foreground Bash that self-detaches (`cmd &`, nohup, a blocking
        # `claude -p`) escapes the gate: the scope filter exempts foreground
        # Bash by design, keyed on the run_in_background FLAG, not command
        # content. Content-parsing was rejected — it would false-gate a
        # clock-out commit whose message contains 'claude'. This pins the gap.
        marker(self.dir, "s", wall="90")
        payload = {"tool_name": "Bash",
                   "tool_input": {"command": "claude -p 'big sweep' &"}}
        rc, _ = run_gate(payload, marker_dir=self.dir, reading="99 40 ? ?")
        self.assertEqual(
            rc, 0,
            "KNOWN GAP: foreground self-detach is not gated (documented). "
            "If this ever returns 2, the scope changed — update SKILL.md + README.")


class TestLegacyMigration(GateBase):
    """A live pre-existing global ~/.claude/night-shift-active must still protect
    (fail LOUD, not silently no-op) — someone armed the old way is still covered."""

    def test_legacy_sentinel_alone_still_gates(self):
        legacy = os.path.join(self._tmp.name, "night-shift-active")
        with open(legacy, "w") as f:
            f.write("90\n")
        # marker dir does not even exist; only the legacy file is armed.
        rc, err = run_gate(FANOUT, marker_dir=self.dir,
                           reading="95 40 ? ?", legacy=legacy)
        self.assertEqual(rc, 2, "legacy global marker is honored")
        self.assertIn("legacy", err.lower(), "deprecation note is surfaced (loud)")

    def test_legacy_wall_respected(self):
        legacy = os.path.join(self._tmp.name, "night-shift-active")
        with open(legacy, "w") as f:
            f.write("70\n")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir,
                         reading="75 40 ? ?", legacy=legacy)
        self.assertEqual(rc, 2, "legacy file's wall (70) applies")

    def test_legacy_min_with_marker(self):
        # Legacy file wall 95 + a per-session marker wall 80 -> min (80) applies.
        legacy = os.path.join(self._tmp.name, "night-shift-active")
        with open(legacy, "w") as f:
            f.write("95\n")
        marker(self.dir, "sessNew", wall="80")
        rc, _ = run_gate(FANOUT, marker_dir=self.dir,
                         reading="85 40 ? ?", legacy=legacy)
        self.assertEqual(rc, 2, "min across legacy + marker")


class TestHermeticity(GateBase):
    """Prove the suite cannot touch the network or the real OAuth credential."""

    def test_hermetic_injection_never_calls_usage_check(self):
        # BEHAVIORAL proof (not a source-order string match, which passes
        # vacuously off the docstring): repoint usage-check at a canary that
        # touches a sentinel iff it runs, arm a shift, inject a reading, and
        # assert the gate NEVER executed the canary. If the injection seam ever
        # rots into always shelling out, the sentinel appears and this fails.
        canary_dir = os.path.join(self._tmp.name, "canary")
        os.makedirs(canary_dir)
        touched = os.path.join(canary_dir, "usage-check-ran")
        fake_usage_check = os.path.join(canary_dir, "usage-check")
        with open(fake_usage_check, "w") as f:
            f.write("#!/bin/sh\ntouch '%s'\necho '99 40 ? ?'\n" % touched)
        os.chmod(fake_usage_check, 0o755)

        marker(self.dir, "s", wall="90")
        # The gate resolves USAGE_CHECK from HOME/.claude/skills/...; override
        # HOME so its usage-check path lands on our canary, AND inject a reading.
        skills_dir = os.path.join(
            canary_dir, ".claude", "skills", "night-shift", "scripts")
        os.makedirs(skills_dir)
        os.rename(fake_usage_check, os.path.join(skills_dir, "usage-check"))
        rc, _ = run_gate(FANOUT, marker_dir=self.dir, reading="80 40 ? ?",
                         extra_env={"HOME": canary_dir})
        self.assertEqual(rc, 0, "injected 80 is under wall -> allow")
        self.assertFalse(
            os.path.exists(touched),
            "usage-check (network + OAuth cred) ran despite injected reading")

    def test_hermetic_no_injection_would_call_usage_check(self):
        # Control: with NO injection, the gate DOES shell out — proving the
        # canary above is wired correctly and the previous test isn't vacuous.
        canary_dir = os.path.join(self._tmp.name, "canary2")
        skills_dir = os.path.join(
            canary_dir, ".claude", "skills", "night-shift", "scripts")
        os.makedirs(skills_dir)
        touched = os.path.join(canary_dir, "usage-check-ran")
        uc = os.path.join(skills_dir, "usage-check")
        with open(uc, "w") as f:
            f.write("#!/bin/sh\ntouch '%s'\necho '80 40 ? ?'\n" % touched)
        os.chmod(uc, 0o755)
        marker(self.dir, "s", wall="90")
        run_gate(FANOUT, marker_dir=self.dir, reading=None,
                 extra_env={"HOME": canary_dir})
        self.assertTrue(
            os.path.exists(touched),
            "without injection the gate must shell out (canary wiring proof)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
