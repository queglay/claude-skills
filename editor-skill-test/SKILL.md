---
name: editor-skill-test
description: Test an editor skill, one that rewrites a provided artifact and whose correctness depends on preserving the author's voice (the humanizer is the canonical case). Use instead of skill-test when the skill edits given prose rather than steering the model's own generation. Verifies preservation and discrimination against provenance-labelled fixtures, not behaviour-presence.
---

# Editor Skill Test

Test an *editor* skill: one that takes a provided artifact (usually prose) and rewrites it, where success is defined by what it preserves as much as by what it changes. The humanizer is the canonical case.

Use this instead of [`skill-test`](../skill-test/SKILL.md) whenever the skill edits a supplied artifact and its correctness depends on the author's voice. Use `skill-test` for *steering* skills, where the skill shapes the model's own generation and a neutral prompt checks for a behaviour.

## Why the steering harness misleads here

`skill-test` verifies **behaviour-presence**: a neutral prompt triggers, the skill steers the model's own output, and you check the output by rate. For an editor skill that model breaks in three ways.

1. **A neutral prompt is unsatisfiable.** The artifact you feed the skill necessarily already contains (or lacks) the exact patterns under test. Stimulus and behaviour cannot be separated, so `skill-test`'s neutral-prompt rule cannot hold.
2. **The success signal is inverted.** The hardest correctness property of an editor skill is *preservation*: leave genuine authorial voice alone. Success often looks like little or no change, which a presence/absence test reads as a *failure*. A clean room can confirm that a pattern was removed but never that voice was preserved, because voice-preservation is defined against the provenance the isolation strips by design.
3. **Calibration inputs cannot be supplied.** An editor skill may take a voice sample or style reference (the humanizer's Voice Calibration). The steering harness has no channel for it, so it always tests a degraded, uncalibrated mode.

A *passing* `skill-test` result for an editor skill is therefore not merely noisy. It is structurally untrustworthy.

## What you need: provenance-labelled fixtures

You cannot judge an edit without knowing where the input came from. Assemble three kinds of fixture, each with known provenance.

- **Known-human**: genuine authorial prose with no AI origin. Correct behaviour is to preserve it. Substantive rewrites here are *false positives* (voice flattening).
- **Known-AI**: text carrying the tells the skill targets. Correct behaviour is to remove the tells. Misses here are *false negatives*.
- **Discrimination traps**: genuine human prose that *superficially resembles* a tell, such as a real em dash the author uses, a genuine three-part list, or a contrast the author actually meant. Correct behaviour is to leave it alone. This is the hardest case, and the one the steering harness cannot even pose.

Keep fixtures short, and hold their provenance out of band. Never let the label leak into the text the skill sees.

## Procedure

Shares the runner and the draft-iteration discipline of [`skill-test`](../skill-test/SKILL.md). What differs is the stimulus and the scoring.

1. **Run through the shared harness.** Feed each fixture as the artifact, invoking the skill via skill-test's runner:
   ```bash
   bash .claude/skills/skill-test/run.sh <skill-or-draft-path> "Humanize the following text:

   <fixture prose>"
   ```

2. **Run each fixture several times.** Writing tells are frequency tendencies, not deterministic triggers: an overused word, an injected comma-join, a manufactured contrast. They fire probabilistically, so a single run is noise and one clean run does not prove a tell absent. Compare *rates* per class, never presence/absence on a single run. And when a change is the *removal* of language that demonstrably steers wrong, the structural argument justifies it on its own; a noisy run that happens to pass must not veto it.

3. **Score each class separately. Never collapse to one number.**
   - Known-human gives a *voice-flattening rate* (false positives). Target near zero.
   - Known-AI gives a *tell-removal rate* (true positives).
   - Discrimination traps give an *over-edit rate*, the human pattern wrongly removed. Target zero.

4. **Judge a language change by the trade, not one axis.** A draft edit that raises tell-removal but also raises voice-flattening or trap over-editing is a regression, not a win. Report all three deltas together.

5. **Supply calibration when the skill accepts it.** If the skill takes a voice sample, include it in the input. An uncalibrated run tests a degraded mode, so treat its preservation numbers as a lower bound and say so.

6. **Apply and simplify** as in skill-test: copy the passing draft back, re-run against the real skill, then reduce the language to its minimal effective form, re-scoring all three classes after each reduction. Stop reducing when any class regresses.

## Provenance: what you assume about where a pattern came from

Before applying any change, ask what you are assuming about where a pattern came from. Is a feature you are protecting deliberate authorial voice, or an artifact of dictation, autocorrect, or an earlier AI pass? Is a contrast or claim genuine, or a frame invented to sound insightful? Do not bake such an assumption into the skill silently. When you surface one, go and read the originals that could be shaping the prose (the author's genuine writing samples, the dictated source, the experience record) and present them so the human can judge too, before the change is locked in. Surfacing the assumption is not enough on its own; the point is to give yourself and the human the chance to look at the source.

When the pattern traces to a specific source that keeps propagating it (a canonical phrasings file, a reused snippet, an anchored entry), **flag that source by name and exact location, and map where it has spread**, so the human can fix it at the root contributor rather than patching each downstream copy. If the root is a "sacred" or anchored source, never edit it silently: flag it and let the human edit it (or authorise the edit).

## Boundary

- Editing a provided artifact where voice matters: use **this skill**.
- Steering the model's own generation: use [`skill-test`](../skill-test/SKILL.md).
- The runner (`run.sh`) and the cross-context-confounds reflection live in `skill-test`. This skill reuses them and adds provenance, the writing-tell rate discipline, and the fixture-based preservation and discrimination method on top.
