# claude-skills

A collection of reusable Claude Code skills.

## Installation

Clone the repo and symlink the skills you want into your Claude Code skills directory:

```bash
git clone https://github.com/queglay/claude-skills ~/git/claude-skills
ln -s ~/git/claude-skills/skill-test <your-claude-skills-dir>/skill-test
```

## Skills

| Skill | Description |
|-------|-------------|
| [skill-test](skill-test/) | Test a skill in an isolated Claude session with no project or user CLAUDE.md, hooks, or other context leaking in. |
