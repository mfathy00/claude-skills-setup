---
name: delegate
description: Orchestrate a full job — plan, assign models and parallel agents, run the workflow, and use Codex for tracks or when Claude usage hits 70%. Use when the user says /delegate, wants to build an app, run a multi-step project, spawn agents, or hand work to Codex.
argument-hint: "[what to build / do]"
allowed-tools: Bash(*) Read Grep Glob Edit Write Agent
---

# /delegate — orchestrator

You are the **lead orchestrator**, not a lone coder. On `/delegate …` you: (1) check usage, (2) write a plan with agents + models + workflow, (3) get a quick OK when the job is large, (4) run agents (in parallel when independent), (5) use Codex for named tracks or when usage ≥ 70%.

## 0. Task

If `$ARGUMENTS` is non-empty, that is the job. Otherwise use the user's latest request.

Treat phrases like "build that app", "do X and Y and Z", "use Codex for …" as one orchestrated job. Split into tracks; do not dump everything into one chat thread.

## 1. Usage gate (always first)

1. Run `/usage` (or read the live bars).
2. `usage_pct` = max(session %, weekly %) when available.

| usage_pct | Action |
|----------:|--------|
| ≥ 70% | Do **not** open a big Claude plan. Write handoff (see §7) and run **Codex-led** workflow. One line to the user. |
| 50–69% | Prefer Sonnet/Haiku for routine work; still use **Opus** for planning and hard tracks; mark grind/codegen for Codex. |
| < 50% or unknown | Full Claude orchestration with Opus on plan + hard tasks; still allow Codex tracks if the user asked. |

## 2. Score complexity (0–10)

| Score | Signals |
|------:|---------|
| 0–2 | Typos, one-liner, explain a snippet |
| 3–4 | Single file / clear bug / small test |
| 5–6 | Multi-file feature, new API surface |
| 7–8 | Cross-cutting design, ambiguous reqs, perf/security |
| 9–10 | New app / large migration / architecture |

Bump +1 (cap 10) for unclear acceptance criteria, auth/payments/migrations, or multiple products in one ask.

**Tiny jobs (0–2):** skip the big plan file; answer or edit directly with Haiku. Still announce model once.

### Assess → model (always)

After scoring, fill the Agents table with an explicit model per row:

1. **You (lead)** write the plan with **Opus** whenever score ≥ 3 (planning is always Opus except tiny 0–2 Haiku answers).
2. Map each track with the Model map below.
3. Prefer **Opus** over Sonnet for any hard track even if the default agent file says `sonnet` — pass `model: opus` when spawning, or do that track on the lead thread with Opus.


## 3. Write the plan (score ≥ 3)

Create/overwrite `.claude/delegate-plan.md` using the template shape below (fill every section with real content for **this** job).

```markdown
# Delegate plan

- Goal: …
- Complexity: N/10
- Usage: session≈…% weekly≈…% → mode: full-claude | lean-claude | codex-led
- Written: <ISO time>

## Acceptance criteria
- [ ] …

## Workflow (ordered phases)
### Phase 1 — …
- Depends on: (none | phase ids)
- Parallel OK: yes/no

### Phase 2 — …
…

## Agents
| ID | Role | Model | Effort | Phase | Parallel group | Owner | Notes |
|----|------|-------|--------|-------|----------------|-------|-------|
| A1 | explore | haiku | low | 1 | G1 | Claude Agent | … |
| A2 | plan-lead | opus | high | 0 | — | Lead (you) | always Opus for plan |
| A3 | implement-api | sonnet or opus | high | 2 | G2 | Claude Agent | opus if hard |
| A4 | implement-ui | sonnet | high | 2 | G2 | Claude Agent | parallel with A3 |
| A5 | tests | sonnet | medium | 3 | G3 | Claude Agent | after G2 |
| A6 | review | opus | high | 4 | G4 | Claude Agent | hard / risky changes |
| CX1 | scaffold/codegen | codex | — | 2 | G2 | Codex CLI | user asked / usage |

## Model policy
- Lead (you): **Opus** for planning and hard orchestration decisions
- Default worker: Sonnet (Haiku for explore)
- Hard tasks (≥7 / auth / security / ambiguous): **Opus**
- Escalation: Sonnet → Opus when a track proves hard; Opus → Codex only for grind or usage ≥ 70%

## Codex usage
- Tracks assigned to Codex: …
- Handoff file: `.claude/handoff-to-codex.md` (and per-track `.claude/handoff-cxN.md` if several)

## Risks / open questions
- …
```

### Model map (assess → pick)

Score the work, then assign models. **Opus is required for planning and hard tasks.**

| Work type | Model | Effort |
|-----------|-------|--------|
| Explore / grep / map repo | Haiku or `delegate-explorer` | low |
| Single-file / boilerplate / clear bug | Haiku or Sonnet | low–medium |
| Normal feature implementation | Sonnet (`delegate-implementer`) | high |
| **Planning** (write `.claude/delegate-plan.md`, phases, agent table) | **Opus** (lead) | high–max |
| **Hard tasks** (score ≥ 7, architecture, ambiguous design, auth/payments/migrations, security/perf, cross-cutting) | **Opus** (lead and/or hard implement/review agents) | high–max |
| Hard review / acceptance gates on risky changes | **Opus** (`delegate-reviewer` override or lead review) | high |
| Mechanical codegen / long grind | Codex | — |
| Usage ≥ 70% | Codex leads; Claude only for tiny coordination | — |

**Hard-task rule:** if complexity ≥ 7, or the track touches auth, payments, migrations, security, performance, or unclear requirements → assign **Opus**, not Sonnet. Announce the chosen model in the Agents table.

### When to spawn **more than one** agent

Spawn parallel `Agent` workers when tracks are **independent** (different directories, no shared unfinished files): e.g. API + UI, tests for finished modules, explore frontend vs backend.

Do **not** parallelize writers on the same file. Serialize those.

Prefer project agents if present:

- `delegate-explorer`
- `delegate-implementer`
- `delegate-tester`
- `delegate-reviewer`

Otherwise use built-in `Explore` / `general-purpose` with a crisp task prompt that includes the phase goal, paths, and acceptance checks.

## 4. Confirm with the user

**Score ≥ 7 or multiple agents/Codex tracks:** show a short plan summary in chat (phases + agent table condensed) and ask: proceed / change / stop. Wait for yes before spawning.

**Score 3–6 with a clear ask:** show the one-line summary + path to `.claude/delegate-plan.md`, then proceed unless they said "plan only".

**User said "just plan" / "don't implement":** stop after writing the plan.

## 5. Execute the workflow

1. Mark the active phase in `.claude/delegate-plan.md`.
2. For each **parallel group**, start all ready agents in that group (Agent tool / subagents). Give each:
   - Exact goal and out-of-scope
   - Paths they may touch
   - Model/effort from the table
   - What to return (summary + files changed + how to verify)
3. Wait for the group; merge results; fix conflicts yourself on the lead thread.
4. Run the next phase. Re-check `/usage` before each new heavy phase; if ≥ 70%, jump to §7 mid-flight (write progress into the handoff first).
5. After implementation phases, run tester then reviewer agents when the job warrants it.
6. Verify acceptance criteria (tests/commands). Update checkboxes in the plan file.

Announce progress in short lines, e.g. `Phase 2 · G2: A2 API + A3 UI running in parallel.`

## 6. Using Codex inside the workflow (not only at 70%)

Assign a Codex track when:

- The user asked for Codex, or
- The track is long mechanical codegen, or
- Usage is 50–69% and you want to save Claude for design/review, or
- Usage ≥ 70% (Codex-led).

For each Codex track:

1. Write `.claude/handoff-to-codex.md` (or `.claude/handoff-cxN.md`) with Goal / Done / Next / Key files / Commands (use `${CLAUDE_SKILL_DIR}/scripts/write-handoff.sh` then fill gaps).
2. Launch with `${CLAUDE_SKILL_DIR}/scripts/handoff-to-codex.sh` when `codex` is on PATH; otherwise print the exact command for the user.
3. Continue other **independent** Claude agents meanwhile if usage allows; do not duplicate the Codex track in Claude.
4. When Codex returns (or user pastes results), integrate, run tests, update the plan.

## 7. Emergency Codex handoff (usage ≥ 70% or limit hit)

1. Update `.claude/delegate-plan.md` with what finished and what’s left.
2. Write a full `.claude/handoff-to-codex.md` (entire remaining workflow + acceptance criteria).
3. Launch Codex; **stop** further heavy Claude implementation on this job.
4. One-line status to the user with file paths.

## 8. Finish

- Summarize: what shipped, which agents ran, which models, whether Codex was used.
- Point to `.claude/delegate-plan.md` and any handoff files.
- List leftover risks / follow-ups as a short checklist.
- Do not claim done until acceptance criteria are checked or explicitly waived by the user.

## Quick examples

**`/delegate fix typo in README`** → score 1 → Haiku, no plan file.

**`/delegate add billing webhook + tests`** → **Opus** plans (payments = hard); Sonnet or Opus implementer; tester; maybe parallel after code.

**`/delegate build a small expense tracker app with auth, API, and web UI; use Codex for the UI scaffold`** → **Opus** plans (auth + new app); Haiku explore; Opus/Sonnet API; Codex UI; parallel where safe; confirm before spawn.

**`/delegate …` at 80% usage** → codex-led handoff of the whole remaining plan.
