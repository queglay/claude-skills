# Contributing

Changes land via GitLab merge requests. Commits may come from a human or an
automated agent; these conventions keep history machine-readable either way,
and deliberately match the counterpart repo — one convention everywhere.

## Commit messages — Conventional Commits

Every commit follows [Conventional Commits](https://www.conventionalcommits.org):

```
<type>(<optional scope>): <summary>

<optional body — what changed and why, wrapped at ~72 columns>

<optional footer — trailers, breaking changes, issue refs>
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `perf`, `test`, `build`, `ci`,
`chore`, `revert`.

**Subject line:** imperative mood ("add", not "added"); keep it short (≤72
characters, aim lower); no trailing period; lower-case after the colon.
**Scope:** optional, a single `[a-z0-9._-]+` token — a skill name is a natural
scope, e.g. `docs(night-shift): clarify the seven-day wall`.

**Body** (encouraged for non-trivial changes): explain the *what* and *why* —
the diff already shows the *how*.

### Examples

```
feat: add night-shift skill for working across usage windows

fix(night-shift): read credentials from CLAUDE_CONFIG_DIR when set

docs: establish commit conventions and enforcement
```

## Enforcement

A `commit-msg` hook validates the format. It is **opt-in** (so it never
surprises a fresh clone). Enable it once per clone:

```
git config core.hooksPath .githooks
```

## Merge requests

- One logical change per MR; keep diffs small and reviewable.
- The MR **title** follows the same Conventional Commits format as a commit
  subject: the project's squash template prefills the squash commit from the
  MR title and description, so a non-conventional title becomes a
  non-conventional commit on merge.
