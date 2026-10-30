# Claude Skills Setup — `/delegate`

A [Claude Code](https://code.claude.com) personal skill that **routes coding work by complexity**, **watches your plan usage**, and **hands off to OpenAI Codex** when usage hits **70%** so you can keep shipping without waiting for the Claude limit to reset.

Repo: [mfathy00/claude-skills-setup](https://github.com/mfathy00/claude-skills-setup)

## What it is (for work)

On a normal day you ask Claude Code to build features, fix bugs, or refactor. This skill turns that into a small ops workflow:

| Step | What happens |
|------|----------------|
| 1. Score the task | 0–10 from size, ambiguity, blast radius (auth, payments, migrations bump the score) |
| 2. Pick a model | Cheap/fast for small jobs; stronger models only when the task needs them |
| 3. Check usage | Reads `/usage` (session + weekly). Takes the higher % |
| 4. Stay or switch | Under 70% → keep going on Claude. At/above 70% → stop heavy Claude work and hand off to Codex with a written brief |

**Why that matters at work:** you burn less premium quota on typos and one-liners, reserve Opus/Sonnet for real design work, and when the five-hour or weekly bar fills up mid-ticket, Codex gets a clean handoff file instead of starting from zero.

## Install on any machine

### Personal (all projects on that machine)

```bash
git clone https://github.com/mfathy00/claude-skills-setup.git
cd claude-skills-setup
./install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/mfathy00/claude-skills-setup.git
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\skills" | Out-Null
Copy-Item -Recurse -Force .\claude-skills-setup\.claude\skills\delegate "$env:USERPROFILE\.claude\skills\"
```

### One repo (share with the team via git)

```bash
mkdir -p .claude/skills
cp -R /path/to/claude-skills-setup/.claude/skills/delegate .claude/skills/
git add .claude/skills/delegate && git commit -m "Add /delegate skill"
```

Requires Claude Code. Codex handoff needs the `codex` CLI on `PATH` (optional until you actually hit 70%).

## How to use

In a project folder, start Claude Code (`claude`), then:

```text
/delegate
/delegate implement pagination on the users API with tests
/delegate we're at high usage — hand off to Codex
```

Or describe a hard task in plain language; Claude should load the skill from its description.

### What you should see

- One short line like: `Complexity 6 → Sonnet (high). Usage ~42%. Continuing here.`
- If usage ≥ 70%: it writes `.claude/handoff-to-codex.md` and tries to launch Codex (or prints the command if `codex` isn’t installed)

### Handoff file

Path: `.claude/handoff-to-codex.md` (project-local, not committed by this skill)

Includes goal, done / in progress, next steps, key files, git status — so Codex continues the same ticket.

Helpers (Git Bash / WSL / macOS / Linux):

```bash
bash ~/.claude/skills/delegate/scripts/write-handoff.sh --reason "usage>=70%" --goal "finish the PR"
bash ~/.claude/skills/delegate/scripts/handoff-to-codex.sh
```

## Model routing (defaults)

| Complexity | Typical work | Model tier |
|-----------:|--------------|------------|
| 0–2 | Typos, renames, short explanations | Haiku (fastest) |
| 3–4 | Single-file fix, small test | Sonnet |
| 5–6 | Multi-file feature, clear refactor | Sonnet (high effort) |
| 7–8 | Cross-cutting design, ambiguous reqs | Opus / strongest |
| 9–10 | Architecture, large migration | Opus (max effort); confirm approach first |

Edit thresholds in `.claude/skills/delegate/SKILL.md` if your team prefers different cutoffs or a different handoff % than 70.

## Layout

```text
.claude/skills/delegate/
  SKILL.md                 # Claude Code skill
  scripts/
    write-handoff.sh       # Snapshot git + handoff markdown
    handoff-to-codex.sh    # Launch Codex with the handoff prompt
install.sh                 # Copy skill into ~/.claude/skills/delegate
README.md
```

## Update

```bash
cd claude-skills-setup && git pull
./install.sh
```

## Privacy

This repo has **no secrets** — only skill text and scripts. Handoff files are written in **your** project’s `.claude/` when you run the skill; they are not part of this repository.

## License

Use and adapt freely for your own Claude Code / Codex workflow.
