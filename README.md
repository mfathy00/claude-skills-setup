# Claude Skills Setup — `/delegate`

A small [Claude Code](https://code.claude.com) skill for planning, assigning scoped
Claude workers, and handing explicitly approved tracks to Codex. It is a set of
instructions plus local helpers—not a quota API, model switcher, or security
boundary. Tiny jobs should stay tiny.

```text
/delegate implement pagination on the users API with tests
/delegate plan only: migrate payments to Stripe
/delegate build an expense tracker; propose Codex for the UI scaffold
```

## Safety and routing

1. **Intent first:** plan-only never launches implementation or Codex, including
   when usage is high. Tool permissions still apply.
2. Write a scoped plan and verifiable acceptance criteria. Confirm complex jobs,
   multi-worker execution, and the scope/provider of Codex tracks before dispatch.
   An explicit request to execute that exact Codex scope can already be approval.
3. Use independent agents only where useful; do not give overlapping files to
   concurrent writers. After approval, dispatch that scope without repeated prompts.
4. If a current usage observation reaches 70%, propose a Codex continuation; do
   not treat quota pressure as permission. Unknown usage means conservative
   coordination, not automatic expensive fan-out.
5. Review outputs and run checks. Report actual evidence, blockers, and models
   observed by the runtime—not just the model names requested in the plan.

| Agent | Purpose | Requested default |
|---|---|---|
| `delegate-explorer` | Read-only mapping (`Read`, `Grep`, `Glob`; no shell) | Haiku |
| `delegate-implementer` | One scoped implementation track | Sonnet |
| `delegate-tester` | Authorized checks; fixes only if assigned | Sonnet |
| `delegate-reviewer` | Read-only risk/acceptance review; no patching or shell | Opus |

Opus is a **preference** for planning/hard work, not a claim that the current lead
can switch itself. Explicit model requirements must not be silently substituted.
Actual model and quota remain `unknown` when the runtime does not expose them.
`/usage` is an interactive Claude Code command, not a command these scripts run.

## Requirements and platforms

- Bash, Git, and Python **3.9+** (standard library only; no pip packages).
- Claude Code for the skill; Codex CLI installed, authenticated and on the same
  shell's `PATH` only when launching a Codex track.
- Handoff helpers require an initialized Git working tree with at least one
  commit. They work from its root or a subdirectory.
- macOS/Linux: run the Bash commands below. On Windows use **WSL with Bash** and
  install the tools inside that WSL environment. Git Bash may work with compatible
  Git/Python/Codex binaries but is not covered by CI. Native PowerShell copying
  alone is not a supported installation/runtime. Do not mix Windows and WSL homes.

No helper installs software, logs in, or edits global Claude/Codex configuration.
The installer intentionally copies only this skill and its four named agents.

## Install

### Personal (all projects)

```bash
git clone https://github.com/mfathy00/claude-skills-setup.git
cd claude-skills-setup
bash install.sh
```

`./install.sh` also works from a normal Git checkout (the executable bit is tracked).
Using `bash` is supported even when a download loses file modes. A fresh install
creates `~/.claude/skills/delegate` and the four `~/.claude/agents/delegate-*.md`
files. Identical copies are left unchanged. Unrelated skills/agents are untouched.

### Project-local (share with the team)

```bash
bash /path/to/claude-skills-setup/install.sh --dest /path/to/project/.claude
```

Review the installed files and commit only the skill and four agents—not backups
or task state. Add the exclusions in the privacy section to that project's
`.gitignore` **before** using `/delegate`. The installer does not edit it for you.

### Update without losing customizations

```bash
cd claude-skills-setup
git pull --ff-only
bash install.sh
# If a managed destination differs, review local customizations first, then:
bash install.sh --replace
```

Without `--replace`, any conflicting target aborts the whole install before
replacing files. With `--replace`, the prior skill directory (including custom
files) and each replaced agent are moved intact into a unique
`.claude/.delegate-backups/install-XXXXXXXX/before/` directory. The new copy is
staged before replacing anything; the backup/recovery path is printed. This is
replacement with backup, **not an automatic merge**—reapply desired customizations
from the backup after review. Backups are never automatically deleted.

Failed installs attempt automatic rollback, preserving the failed new copies
under that transaction's `failed/` directory. If rollback itself fails, the error
names the recovery directory; stop and restore manually before retrying. A lock
prevents concurrent installers. An abrupt kill or power loss may leave a lock
and partial transaction: inspect both before removing the stale lock.

To roll back a completed update, stop active agents, inspect the transaction's
`installed-paths.txt`, and move each current listed target into a separate recovery
folder. Move its matching `before/` item back to the original destination. If no
`before/` item exists, that target was newly installed; keep its moved copy but do
not restore it. Never delete current customizations just to roll back. Do not run
an installer concurrently with recovery. Symlinked source/destination state is
refused rather than followed.

## Codex handoff: explicit, isolated, single-use

From the project, choose a new run ID and a track ID. Set `SKILL_DIR` to the
personal install below, or to the project's `.claude/skills/delegate`.

```bash
SKILL_DIR="$HOME/.claude/skills/delegate"
bash "$SKILL_DIR/scripts/write-handoff.sh" \
  --run-id pagination-001 --track CX1 --reason approved-track \
  --goal 'Implement users API pagination and its acceptance tests'
```

Omit `--run-id` to generate one; the helper prints the ID and draft path. Fill
**every section** of `.claude/delegate-runs/pagination-001/CX1/handoff.md`, including
acceptance criteria, completed work, next steps, allowed paths and constraints.
Use `None` where accurate, not empty sections or TODO/TBD placeholders. Inspect it
for private information. `--model MODEL` on the writer requests a specific Codex
model; it does not prove availability or actual runtime identity.

After the user has approved this exact scope, provider, and write mode:

```bash
bash "$SKILL_DIR/scripts/handoff-to-codex.sh" \
  --run-id pagination-001 --track CX1 --approve --sandbox workspace-write
```

The default sandbox is `read-only`; choose `workspace-write` only for approved
edits. `--plan-only` suppresses launch even with `--approve`. The approval flag is
an assertion by the caller, not a UI confirmation or authentication mechanism.

The helper uses `codex exec`, a dedicated `--output-last-message` path, task text
on stdin (not shell evaluation/process arguments), no permission escalation, and
network disabled in the workspace sandbox. See the official
[CLI reference](https://learn.chatgpt.com/docs/cli/reference) and
[approval/sandbox guidance](https://learn.chatgpt.com/docs/agent-approvals-security).
Local Codex configuration, integrations and platform sandbox support still
matter; review them before sending sensitive context. This wrapper is not a
sandbox around arbitrary installed plugins or a hostile local process.

Each track has its own directory:

```text
.claude/delegate-runs/<run-id>/
  plan.md                      # orchestrator's plan, when permitted
  <track>/
    handoff.md                 # reviewed task text
    manifest.json              # repository/run/track identity and context hash
    started.json               # exclusive single-use launch marker
    result.md                  # Codex's final message (not proof of success)
    outcome.json               # exit code and whether a nonempty result exists
```

Launch fails closed for missing/incomplete drafts, mismatched identity, symlinks,
unsafe paths, existing output/launch markers, age over 24 hours, or Git context
changes (HEAD/branch, tracked changes, untracked paths/content). Ignored files,
submodule internals, and external services are **not fully fingerprinted**; assess
those dependencies yourself. Generated run state is excluded from the hash.
A process exit of zero plus a nonempty result still needs acceptance review.

Create drafts after other preparatory edits. If context changes, inspect the
changes and create a fresh track; don't edit the manifest to bypass checks. If a
run fails or is interrupted, inspect its output and repository changes before
creating a new track. No automatic retry of potentially paid work. If Codex is
missing, the draft is preserved and no start marker is written; install/log in
manually and rerun the same launch command.

Independent read-only tracks can run in parallel. **Use separate Git worktrees
for concurrent writers**: unique handoff files do not prevent source-file races.
Context validation may deliberately reject a second launch after the first worker
has changed a shared working tree.

### Compatibility notes

Existing script names and `--goal`/`--reason` remain. Shared legacy
`.claude/handoff-to-codex.md` and `handoff-from-codex.md` are no longer auto-launched
or overwritten. The launcher now requires `--run-id` and `--approve`; new handoffs
require a committed Git repository. `--out` (writer), `--handoff` and `--output`
(launcher) are optional assertions of the **exact canonical run/track path**, not
arbitrary output locations. Recreate legacy handoffs as reviewed new drafts.

## Privacy and version control

Task plans, prompts, output, filenames and backups may contain confidential
project/user data. Git ignore is not encryption, and does not untrack previously
committed files. Do not include credentials; inspect context before handing it to
another provider. Deleting a local artifact does not delete provider-side records.

Add these patterns to **each consuming project's** `.gitignore` (or its local
`.git/info/exclude` for private-only exclusions), and verify with `git status`:

```gitignore
.claude/delegate-runs/
.claude/delegate-plan.md
.claude/handoff-*.md
.claude/.delegate-backups/
.claude/.delegate-install.lock/
```

The helpers create new state with a restrictive umask where supported. They do
not upload files themselves until an explicitly approved Codex launch, but Codex
will receive the task text and can read project context. Choose retention and
backup cleanup deliberately; nothing here automatically purges your history.

## Tests and CI

```bash
bash tests/run.sh
```

Runs Bash syntax checks plus standard-library `unittest` integration tests using
isolated temporary homes/repositories and **fake Codex executables only**. Covers
install conflicts/backups/rollback, preflight and path safety, approval/plan-only,
stale/missing/incomplete handoffs, parallel tracks, duplicate launches, missing
CLI, nonzero exits and empty outputs. GitHub Actions runs on Linux and macOS.
These tests do not validate a live Claude session, Codex service, model routing,
authentication, sandbox behavior, or quota readings; no paid model calls occur.

## License follow-up

The repository's existing permission statement is: “Use and adapt freely for
your Claude Code / Codex workflow.” There is no named license file yet. The owner
should clarify licensing before broader redistribution; this change does not
select a new license on their behalf.
