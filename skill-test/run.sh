#!/bin/bash
# Isolated skill test runner.
# Usage: run.sh <skill-name-or-path> "<prompt>"
# Run from the repo root so .claude/skills/ is discoverable when passing a skill name.
set -euo pipefail

if [ $# -lt 2 ]; then
  echo "Usage: run.sh <skill-name-or-path> <prompt>" >&2
  exit 1
fi

SKILL_ARG="$1"
PROMPT="$2"

if [ -f "$SKILL_ARG" ]; then
  SKILL_FILE="$SKILL_ARG"
else
  SKILL_FILE=".claude/skills/$SKILL_ARG/SKILL.md"
fi

if [ ! -f "$SKILL_FILE" ]; then
  echo "Skill not found: $SKILL_FILE" >&2
  exit 1
fi

SKILL_CONTENT=$(awk '/^---$/{n++; if(n==2){found=1; next}} found{print}' "$SKILL_FILE")

FAKE_HOME=$(mktemp -d)
WORKDIR=$(mktemp -d)
trap 'rm -rf "$FAKE_HOME" "$WORKDIR"' EXIT INT TERM

mkdir -p "$FAKE_HOME/.claude"
ln -s "$HOME/.claude/.credentials.json" "$FAKE_HOME/.claude/.credentials.json"

( cd "$WORKDIR" && \
  HOME="$FAKE_HOME" CLAUDE_CODE_DISABLE_AUTO_MEMORY=1 \
  claude -p "$PROMPT" \
    --dangerously-skip-permissions \
    --append-system-prompt "$SKILL_CONTENT" \
    2>&1
)
