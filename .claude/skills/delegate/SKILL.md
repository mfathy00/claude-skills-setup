---
name: delegate
description: Route work by complexity across Claude models, check plan usage, and hand off to Codex when usage is at or above 70%. Use when starting a non-trivial coding task, when the user says delegate / switch models / check usage, or when a limit warning appears.
argument-hint: "[task description]"
allowed-tools: Bash(*) Read Grep Glob Edit Write Agent
---

# Delegate: model routing + Codex handoff

Run this skill at the start of non-trivial work and again whenever usage may have climbed (long sessions, big refactors, many tool calls).

## 0. Arguments

If `$ARGUMENTS` is non-empty, that is the task. Otherwise use the user's latest request as the task.

## 1. Check usage first (hard gate)

Before choosing a model or doing heavy work:

1. Run `/usage` (or read the live usage indicator if already shown).
2. Parse the **current session** (5-hour) bar and the **weekly** bar if shown.
3. Take `usage_pct` = the higher of those two percentages.

If either bar is **≥ 70%**:

- Do **not** start a large new Claude turn.
- Jump to **§4 Codex handoff** immediately with reason `usage≥70%`.
- Tell the user in one line that usage is high and you are handing off to Codex.

If usage cannot be read (API-key / pay-as-you-go with no bar):

- Skip the gate.
- Still write a short usage note in the handoff file if you later switch models for other reasons.

## 2. Score complexity (0–10)

Score the task once. Be conservative: when unsure, score higher.

| Score | Signals |
|------:|---------|
| 0–2 | Typo, rename, one-liner, explain a short snippet |
| 3–4 | Single file change, clear bugfix, small test |
| 5–6 | Multi-file feature, non-trivial refactor, new API surface |
| 7–8 | Cross-cutting design, ambiguous requirements, perf/security |
| 9–10 | Architecture, large migration, novel algorithms, high blast radius |

Also bump +1 (cap 10) if any of these apply: unclear acceptance criteria, touches auth/payments/data migration, or needs a design choice first.

## 3. Pick Claude model and effort

Map score → model. Use `/model` (or the Task/Agent model override for subagents) for this turn only.

| Score | Model | Effort | Style |
|------:|-------|--------|-------|
| 0–2 | Haiku (fastest available) | low | Answer directly; minimal exploration |
| 3–4 | Sonnet | medium | Focused edits; read only what you need |
| 5–6 | Sonnet | high | Plan briefly, then implement |
| 7–8 | Opus (or strongest available) | high | Explore, propose approach, then implement |
| 9–10 | Opus | max / xhigh | Design first; get user OK on approach before large edits |

Rules:

- Prefer the **cheapest** model that can finish the job well.
- Do not escalate mid-task unless the current model is stuck after a real attempt.
- If Opus is unavailable, use the strongest allowed Sonnet and say so once.
- For forked subagents (`Agent` / explore), pass the same model tier so children do not silently burn Opus.

Announce in one short line before working, e.g. `Complexity 6 → Sonnet (high). Usage ~42%. Continuing here.`

## 4. Codex handoff (usage ≥ 70% or user asks)

Goal: Codex can continue **without** re-discovering context.

### 4.1 Write the handoff pack

Create or overwrite `.claude/handoff-to-codex.md` in the project root (create `.claude/` if needed) with:

```markdown
# Handoff: Claude Code → Codex

- Written: <ISO timestamp>
- Reason: <usage≥70% | user request | model limit | other>
- Claude usage: session=<n>% weekly=<n>% (or unknown)
- Complexity score: <0–10>
- Last Claude model: <name>
- Branch: <git branch>
- HEAD: <short sha>
- Working tree: <clean | dirty>

## Goal
<one paragraph: what done looks like>

## Done already
- ...

## In progress
- ...

## Next concrete steps (ordered)
1. ...
2. ...

## Key files
- path — why it matters

## Commands already run (and results)
- `...` → ...

## Constraints / do not
- ...

## Open questions
- ...
```

Fill every section from the real session. Prefer facts over speculation. Include failing test names and exact error lines when you have them.

Also run the helper (preferred) so a machine-readable snapshot is saved:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/write-handoff.sh \
  --reason "usage>=70%" \
  --goal "$ARGUMENTS"
```

If the helper is missing, write the markdown file yourself as above.

### 4.2 Freeze git state for Codex

Without committing secrets:

1. `git status -sb` and `git diff` (staged + unstaged) → append a short summary under **In progress**.
2. If there are important uncommitted edits, leave them on disk; do **not** `git reset --hard`.
3. Optionally stash only if the user asked; default is leave the tree as-is for Codex.

### 4.3 Launch or instruct Codex

Prefer launching Codex in the same repo with the handoff as the seed prompt:

```bash
bash ${CLAUDE_SKILL_DIR}/scripts/handoff-to-codex.sh
```

That script:

1. Ensures `.claude/handoff-to-codex.md` exists.
2. Starts Codex (`codex`) in the project root with a prompt that says: read the handoff file, continue from **Next concrete steps**, do not redo completed work.

If `codex` is not on PATH:

- Tell the user the handoff file path.
- Give them this exact command to run:

```bash
codex "Read .claude/handoff-to-codex.md and continue from Next concrete steps. Do not redo Done already. Report when the Goal is met."
```

### 4.4 Stop Claude work on this task

After a successful handoff write (and launch if possible):

- Stop implementing this task in Claude Code.
- One-line status to the user: handoff written, Codex started (or needs manual start), path to the file.
- Do not keep burning Claude tokens on the same task until usage drops or the user says to resume in Claude.

## 5. Mid-task usage recheck

While still on Claude:

- Recheck usage after large batches of tool calls, before starting a new major phase, or if a limit warning appears.
- If `usage_pct` crosses 70% mid-task → §4 immediately (write handoff with current progress first).

## 6. Returning from Codex → Claude

When the user is back on Claude and usage is under 70%:

1. Read `.claude/handoff-from-codex.md` if present, else ask what Codex finished.
2. Verify with tests / diff before claiming done.
3. Delete or archive handoff files only if the user wants cleanup.

## Quick examples

- "fix typo in README" → score 1 → Haiku, no handoff.
- "add pagination to the users API + tests" → score 5–6 → Sonnet high.
- "redesign auth to passkeys across web + mobile" → score 9 → Opus; if usage ≥70% → Codex handoff instead.
- User: "we're at 80%, keep going" → §4 only, no more Claude implementation.
