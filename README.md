# Claude Skills Setup â€” `/delegate`

A small [Claude Code](https://code.claude.com) skill for planning, assigning scoped
Claude workers, and handing explicitly approved tracks to Codex. It is a set of
instructions plus local helpersâ€”not a quota API, model switcher, or security
boundary. Tiny jobs should stay tiny.

```text
/delegate implement pagination on the users API with tests
/delegate plan only: migrate payments to Stripe
/delegate build an expense tracker; propose Codex for the UI scaffold
```

## Bounded super-agent and folder factory

The [runtime guide](docs/SUPERAGENT.md) adds durable **Claude + Codex** coordination:
scoped continuing sessions, event inboxes and recall, a read-only task-folder
watcher, explicit specialist/model routing, and plan → build → tool checks →
security review → owner acceptance. Four workers by default, configurable 1–6.

```bash
python3 -m examples.superagent.demo  # offline continuing-ticket + factory demo
bash install.sh                    # Claude skill with passive bundled controller
bash install.sh --client codex     # optional self-contained Codex personal skill
```

The AI lead proposes plans/routes; the controller enforces immutable approvals,
revision manifests, bounds and conflict gates. Empty/waiting backlog makes no
model calls. New or changed tasks are never automatically authorized. Routine
work can use an approved lighter model; planning/security and high-risk work keep
strong-model floors. Tests run through fixed tools, not a model merely to execute.

[Setup, examples, security, coverage matrix, cost limits and pros/cons →](docs/SUPERAGENT.md)

This is a tested **mock-first foundation**, not full article parity or a deployed
24/7 platform. No live model/container verification or zero-extra-cost guarantee.
Live use requires approved models/accounts, isolated hosts and external billing
controls. Worktrees are not security isolation; no automatic merge/deployment or
PR publishing. Existing `/delegate` handoff and interactive Codex behavior below
remain available; installation does not start the new service.

## Safety and routing

1. **Intent first:** plan-only never launches implementation or Codex, including
   when usage is high. Tool permissions still apply.
2. Write a scoped plan and verifiable acceptance criteria. Clear score **3â€“6**
   execution requests proceed after a one-line summary, including independent
   parallel Claude workers. Multiple workers alone do not add a confirmation gate.
   Confirm score **â‰¥7** and Codex scope/provider/mode unless already specifically
   approved. A plan-only request never authorizes execution.
3. Use independent agents only where useful; never give overlapping files to
   concurrent writers. Unknown usage means **normal full-Claude orchestration**,
   including parallel agents; honestly state that usage was not observed.
4. Offer **Auto-Codex at â‰¥70%: yes/no** in each job's plan (default no). An explicit
   user opt-in covers the remaining scope, provider, runtime mode and sandbox, so
   an observed threshold can trigger a validated handoff **without repeat consent**.
   Without matching approval, ask before switching. Unknown usage never invents a
   threshold trigger. Opt-in expires with the job, is revocable, and never overrides
   plan-only, scope limits or interactive security prompts.
5. Review outputs and run checks. Report actual evidence, blockers, and models
   observed by the runtimeâ€”not just the model names requested in the plan.

| Agent | Purpose | Requested default |
|---|---|---|
| `delegate-explorer` | Read-only mapping (`Read`, `Grep`, `Glob`; no shell) | Haiku |
| `delegate-implementer` | One scoped implementation track | Sonnet; explicit `model: opus` for hard work |
| `delegate-tester` | Authorized checks; fixes only if assigned | Sonnet |
| `delegate-reviewer` | Read-only risk/acceptance review; lead supplies Git views | Opus |

Opus is a **preference** for planning/hard work, not a claim that the current lead
can switch itself. Explicit model requirements must not be silently substituted.
Actual model and quota remain `unknown` when the runtime does not expose them.
`/usage` is an interactive Claude Code command, not a command these scripts run.
Hard implementation (auth/payments/migrations/security/performance/ambiguous design
or score â‰¥7) goes to **delegate-implementer with `model: opus`**, not the read-only
reviewer. Planning uses the Opus lead; review uses the Opus reviewer.

A plan can record this explicit job-level consent:

```text
Auto-Codex at â‰¥70%: yes
Opt-in evidence: user approved Codex for this job's remaining API/test scope
Approved runtime: exec; sandbox: workspace-write
Exclusions: no publishing, deployment, or unrelated files
```

The orchestrator must not set yes on its own. It can use `--approve` for a matching,
still-valid opt-in without asking again; changed scope/mode or revoked permission
requires the missing consent. This is an instruction-level consent record, not an
authentication system or a globally persisted preference.

### Useful tools without unrestricted shell access

The skill pre-approves `Agent`, `Edit`, `Write`, read tools, and Bash invocations of
its exact bundled helper paths. These grants reduce per-tool prompts; they do not
turn plan-only into execution or supersede managed deny/ask rules. See the official
[skill tool-permission semantics](https://code.claude.com/docs/en/skills#pre-approve-tools-for-a-skill).

The lead can provide current Git views to the reviewer:

```bash
SKILL_DIR="$HOME/.claude/skills/delegate"  # or the project-local installation
bash "$SKILL_DIR/scripts/review-git.sh" status  # or diff, staged, log
```

Only those four fixed views are accepted (no arbitrary flags). Configured Git
clean/process/smudge filters are refused before inspection; lazy fetches and
transports are disabled. External diff/text converters, pagers, fsmonitor,
signature checks and optional index writes are avoided. Submodules, including gitlink changes, are excluded from these views and handoff fingerprints. The reviewer remains
shell-less and can ask for a fresh view. This is deliberate: a subagent tool list
does not turn Bash into a git-only sandbox; see the official
[subagent tool restrictions](https://code.claude.com/docs/en/sub-agents#restrict-which-tools-a-subagent-can-use).

## Requirements and platforms

- Bash, Git, and Python **3.9+** (standard library only; no pip packages).
- Claude Code for the skill; Codex CLI installed, authenticated and on the same
  shell's `PATH` only when launching a Codex track.
- Handoff helpers require an initialized Git working tree with at least one
  commit. They work from its root or a subdirectory.
- macOS/Linux: run the Bash commands below. **Windows support is WSL-only**:
  install Bash, Git, Python (`python3`), Claude and Codex inside the same WSL
  environment. Native PowerShell and Git Bash are not supported by this package.
  Do not mix Windows and WSL homes. CI covers Linux/macOS, not WSL itself.

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

Review the installed files and commit only the skill and four agentsâ€”not backups
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
replacement with backup, **not an automatic merge**â€”reapply desired customizations
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

With this exact scope, provider and runtime mode approved (including an earlier
matching per-job auto-Codex opt-in), launch without asking for the same consent again:

```bash
bash "$SKILL_DIR/scripts/handoff-to-codex.sh" \
  --run-id pagination-001 --track CX1 --approve --sandbox workspace-write
```

The default sandbox is `read-only`; choose `workspace-write` only for approved
edits. `--plan-only` suppresses launch even with `--approve`. The approval flag is
an assertion by the caller, not a UI confirmation or authentication mechanism.

### Default: unattended exec

The default uses `codex exec`, a dedicated `--output-last-message` path, task text
on stdin (not shell evaluation/process arguments), no permission escalation, and
network disabled in the workspace sandbox. Use it for bounded work that fits
those permissions. A blocked install/fetch is not permission to loosen them.

### Optional: interactive Codex-led continuation

For approved steering or user-reviewed installs/fetches, run in your terminal:

```bash
bash "$SKILL_DIR/scripts/handoff-to-codex.sh" \
  --run-id pagination-001 --track CX1 --approve --interactive --sandbox workspace-write
```

Choose the mode before first launch; a consumed track cannot be relaunched in a
different mode. For a failed exec run, inspect its changes and create a fresh track
before an approved interactive continuation. `--plan-only` suppresses both modes.

Interactive mode inherits your terminal and runs `codex` with the selected
sandbox, `--ask-for-approval on-request`, user-reviewed requests, and network still
disabled inside the workspace sandbox. You can steer the session and approve
specific escalation requests when supported (for example a required package
fetch). It does **not** silently enable network, bypass controls, auto-approve
requests, or edit global settings. Managed restrictions remain in force. The
same job/provider/sandbox consent rules apply; interactive prompts are additional
per-action controls, not repeated approval for the whole job.

When called without a TTY (often from Claude's shell tool), the launcher validates
the draft, prints the exact shell-quoted command to run in your terminal, and exits
**2** without writing a start marker or invoking Codex. That command calls this
launcher again, so stale/changed context is revalidated rather than bypassed.
Do not manufacture a pseudo-terminal to run a real unattended interactive client.

The interactive CLI has no `--output-last-message` equivalent used here. The prompt
asks for `result.md` only when write scope permits; otherwise the summary remains
in the conversation. `outcome.json` records the mode and process exit status, but
zero only means the session ended normallyâ€”not that the task is complete. Inspect
the conversation, changes, checks and any result before accepting the work. Only
exec mode requires a nonempty result file to return success.

See the official [CLI reference](https://learn.chatgpt.com/docs/cli/reference) and
[approval/sandbox guidance](https://learn.chatgpt.com/docs/agent-approvals-security).
Local Codex configuration, integrations and platform support still matter;
review them before sending sensitive context. This wrapper is not a sandbox
around arbitrary installed plugins or a hostile local process.

Each track has its own directory:

```text
.claude/delegate-runs/<run-id>/
  plan.md                      # orchestrator's plan, when permitted
  <track>/
    handoff.md                 # reviewed task text
    manifest.json              # repository/run/track identity and context hash
    started.json               # exclusive single-use launch marker
    result.md                  # final message; optional for interactive sessions
    outcome.json               # mode, exit code, result presence; needs review
```

Launch fails closed for missing/incomplete drafts, mismatched identity, symlinks,
unsafe paths, existing output/launch markers, age over 24 hours, or Git context
changes (HEAD/branch, tracked changes, untracked paths/content). Ignored files,
submodule internals, and external services are **not fully fingerprinted**; assess
those dependencies yourself. Generated run state is excluded from the hash.
A process exit of zero (and, in exec mode, a nonempty result) still needs acceptance review.

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
CLI, nonzero exits and empty outputs. Interactive tests use a fake executable in
a test-only pseudo-terminal; they check inherited terminal streams, explicit
approval/network flags, and no-TTY fallback without running a real client. Fixed
Git views are tested for read-only behavior and refusal of arbitrary commands.
Static policy-contract checks cover routing examples and tool/model declarations;
they are not evidence that a live model will follow every instruction. GitHub
Actions runs on Linux and macOS. Live Claude/Codex behavior, authentication,
permission prompts, model routing and quota readings are not exercised; no paid
model calls occur.

## License

[MIT](LICENSE) (c) 2026 Mohamed F. Deifalla
