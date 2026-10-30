# Claude Code setup — delegate skill

Personal Claude Code skill that:

- Routes tasks by complexity (Haiku / Sonnet / Opus)
- Checks `/usage` and hands off to **Codex** when usage is ≥ 70%
- Writes `.claude/handoff-to-codex.md` so Codex can continue mid-task

## Install on any machine

### Option A — personal skills (all projects on that machine)

```bash
git clone https://github.com/mfathy00/claude-skills-setup.git
mkdir -p ~/.claude/skills
cp -R claude-skills-setup/.claude/skills/delegate ~/.claude/skills/
```

Windows (PowerShell):

```powershell
git clone https://github.com/mfathy00/claude-skills-setup.git
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force .\claude-skills-setup\.claude\skills\delegate "$env:USERPROFILE\.claude\skills\"
```

### Option B — one project (commit with the repo)

```bash
mkdir -p .claude/skills
cp -R /path/to/claude-skills-setup/.claude/skills/delegate .claude/skills/
git add .claude/skills/delegate && git commit -m "Add /delegate skill"
```

## Use

In Claude Code:

```text
/delegate
/delegate fix the flaky auth tests
```

Or just start a hard task — Claude should load the skill from its description.

## Update

```bash
cd claude-skills-setup && git pull
cp -R .claude/skills/delegate ~/.claude/skills/
```

## Layout

```text
.claude/skills/delegate/
  SKILL.md
  scripts/
    write-handoff.sh
    handoff-to-codex.sh
```
