---
name: skill-test
description: Test a skill in an isolated Claude session. Runs the sidecar run.sh which injects skill content via --append-system-prompt into a spawned claude -p process with a temporary HOME — no project or user CLAUDE.md, hooks, or other skills.
---

Test that a skill produces the desired behaviour in a clean session, independent of any project or user context.

## Arguments

```
/skill-test <skill-name> <prompt>
```

Example:
```
/skill-test coding-standards I am implementing a new parser. What requirements apply?
```

The `<prompt>` must be **neutral** — it must not encode or imply the behaviour the skill is supposed to produce. A prompt that already leads the answer makes the test meaningless regardless of whether the skill loaded.

## Procedure

1. **Parse arguments**: Extract `<skill-name>` and `<prompt>` (everything after the skill name).

2. **Run the sidecar**:
   ```bash
   bash .claude/skills/skill-test/run.sh "<skill-name>" "<prompt>"
   ```

3. **Report**: Display the output.

## Iterating on skill language

When the goal is to verify that modified skill language produces the desired result:

1. **Copy to temp**: Copy the skill being modified:
   ```bash
   DRAFT=$(mktemp /tmp/skill-draft-XXXX.md)
   cp .claude/skills/<skill-name>/SKILL.md "$DRAFT"
   ```

2. **Baseline run (negative check)**: Before touching the draft, run the test prompt against the **unmodified** skill. Confirm the result is negative — i.e., the desired behaviour is absent. If the baseline already passes, the planned change is not load-bearing; stop and reconsider the test prompt or the modification.

3. **Edit the draft**: Make language changes only in the draft.

4. **Test with the draft**: Pass the draft path directly — the sidecar accepts either a skill name or a file path:
   ```bash
   bash .claude/skills/skill-test/run.sh "$DRAFT" "<prompt>"
   ```

5. **Iterate**: Compare output against expected findings. If the result is wrong, edit the draft and re-run. Never modify the original skill during iteration.

6. **Apply**: Once the draft produces the desired result, copy it back to the real skill file. Then run one final test against the skill name to confirm.

7. **Simplify**: After success, try reducing the language to its minimal effective form. Re-run after each reduction to catch regressions. Stop when further simplification causes the finding to disappear.

## Important

- `--dangerously-skip-permissions` is required for unattended runs — the session is read-only (exploration only) so this is safe
- For persistent log capture, redirect stdout: `bash .claude/skills/skill-test/run.sh foo "…" > ~/some/path.md`
