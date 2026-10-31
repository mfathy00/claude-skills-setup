# Claude Skills Setup — `/delegate` orchestrator

A [Claude Code](https://code.claude.com) skill that acts as a **lead agent**: it writes a plan, assigns **models + parallel subagents**, runs the workflow, and uses **OpenAI Codex** for named tracks or when Claude usage hits **70%**.

Repo: [mfathy00/claude-skills-setup](https://github.com/mfathy00/claude-skills-setup)

## What it is (for work)

You say something like:

```text
/delegate build an expense tracker with auth, API, and web UI; use Codex for the UI scaffold; I also want tests and a short review
```

Claude (as orchestrator) will:

1. Check `/usage`
2. Score complexity and write `.claude/delegate-plan.md` (phases, agents, models, Codex tracks)
3. Confirm on large jobs, then **spawn agents** (explorer / implementer / tester / reviewer) — **in parallel** when tracks don’t share files
4. Hand Codex its own handoff file for UI/codegen or when usage ≥ 70%
5. Merge results, verify acceptance criteria, summarize

| Piece | Role |
|-------|------|
| `/delegate` skill | Lead orchestrator (plan + dispatch) |
| `delegate-explorer` | Read-only map of the repo |
| `delegate-implementer` | One feature track |
| `delegate-tester` | Run/fix tests |
| `delegate-reviewer` | Acceptance + risk review |
| Codex | Mechanical / long tracks or high Claude usage |

## Install on any machine

### Personal (all projects)

```bash
git clone https://github.com/mfathy00/claude-skills-setup.git
cd claude-skills-setup
./install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/mfathy00/claude-skills-setup.git
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.claude\skills","$env:USERPROFILE\.claude\agents" | Out-Null
Copy-Item -Recurse -Force .\claude-skills-setup\.claude\skills\delegate "$env:USERPROFILE\.claude\skills\"
Copy-Item -Force .\claude-skills-setup\.claude\agents\delegate-*.md "$env:USERPROFILE\.claude\agents\"
```

### One repo (share with the team)

```bash
cp -R claude-skills-setup/.claude/skills/delegate .claude/skills/
cp claude-skills-setup/.claude/agents/delegate-*.md .claude/agents/
git add .claude && git commit -m "Add /delegate orchestrator + agents"
```

Needs Claude Code. Codex tracks need the `codex` CLI on `PATH` (optional until you use them).

## How to use at work

```text
/delegate
/delegate implement pagination on the users API with tests
/delegate build that app and do X Y Z; Codex for the UI
/delegate plan only: migrate payments to Stripe
```

### What you should see

- A plan file: `.claude/delegate-plan.md` (agents table, phases, models, Codex)
- Progress lines: `Phase 2 · G2: API + UI agents running in parallel`
- If usage ≥ 70%: `.claude/handoff-to-codex.md` and Codex-led continuation

### Example agent table (filled by the skill)

| ID | Role | Model | Phase | Parallel | Owner |
|----|------|-------|-------|----------|-------|
| A1 | explore | haiku | 1 | G1 | Claude |
| A2 | plan-lead | **opus** | 0 | — | Lead |
| A3 | implement-api | sonnet or **opus** | 2 | G2 | Claude |
| A4 | implement-ui | — | 2 | G2 | Codex |
| A5 | tests | sonnet | 3 | G3 | Claude |
| A6 | review | **opus** | 4 | G4 | Claude |

## Model + usage policy

The skill **assesses** each track and picks a model:

| Work | Model |
|------|-------|
| Explore / map | Haiku |
| Normal implement / tests | Sonnet |
| **Planning** (always for score ≥ 3) | **Opus** |
| **Hard tasks** (score ≥ 7, auth, payments, migrations, security, perf, ambiguous) | **Opus** |
| Long grind / codegen | Codex |
| Usage ≥ 70% | Codex-led |

| Complexity | Lead behavior |
|-----------:|---------------|
| 0–2 | No big plan; Haiku direct |
| 3–6 | Opus plans; Sonnet workers unless a track is hard |
| 7–10 | Opus plans + hard tracks; show plan; wait for OK before spawning |

| Usage | Mode |
|------:|------|
| < 50% | Full Claude orchestration (Opus on plan + hard) |
| 50–69% | Lean Claude; Opus still for plan/hard; grind → Codex |
| ≥ 70% | Codex-led; Claude stops heavy implementation |

## Layout

```text
.claude/skills/delegate/
  SKILL.md
  templates/delegate-plan.md
  scripts/write-handoff.sh
  scripts/handoff-to-codex.sh
.claude/agents/
  delegate-explorer.md
  delegate-implementer.md
  delegate-tester.md
  delegate-reviewer.md
install.sh
README.md
```

## Update

```bash
cd claude-skills-setup && git pull && ./install.sh
```

## Privacy

No secrets in this repo — skill text, agents, and scripts only. Plan/handoff files are written under **your project’s** `.claude/` when you run `/delegate`.

## License

Use and adapt freely for your Claude Code / Codex workflow.
