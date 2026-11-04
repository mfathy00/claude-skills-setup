# Bounded super-agent runtime · v0.2

A local, mock-first software-factory foundation for **Claude and Codex**. The
existing AI lead proposes the plan and specialist/model routes; a deterministic
controller enforces scope, approvals, durable state and resource limits. Workers
execute bounded turns. Neither backlog text nor model output becomes authority.

This follows the separation of router, isolated workers, event subscriptions and
context references in the [DeepSeek research prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)
and [architecture notes](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/docs/007-architecture.md).
No upstream code was installed, run or copied. **This is not full article parity,
a production platform, or a deployed unattended agent.**

## Start with the offline demonstration

From this checkout, with Python 3.9+ on Linux/macOS (Windows requires WSL):

```bash
python3 -m examples.superagent.demo
bash tests/run.sh
```

The demo exercises a continuing ticket: wait → scoped event and owner message →
exact-session continuation → authorized artifact recall → owner acceptance. It
also proves stop prevents waking, then runs a folder item through mock planning,
building, checks and security review. **Mock checks do not verify project code.**
No model, Docker container, credentials or network is used. Temporary state is
removed. The offline suite separately tests real Git checks and disposable Python
unittest fixtures, plus fake CLI/container lifecycle contracts.

## What is actually implemented

| Area | Shipped | Remaining / limitation |
|---|---|---|
| Planning/router | Existing Claude/Codex lead proposes trusted policy; strong planning stage; deterministic stage/risk/model routing with reasons | No independent open-ended LLM router, recursive agents or arbitrary tool RPC |
| Continuing workers | Durable per-ticket inbox, scoped subscriptions, owned exact CLI sessions, bounded follow-up turns | Input arrives at turn boundaries, not full-duplex steering |
| Context | Immutable hashed artifacts, provenance edges, scoped model-requested recall | Bounded local graph, not global semantic memory |
| Folder backlog | Read-only JSON adapter, revision deduplication, dependency validation, deterministic polling, exact preapproved manifest | No board API or automatic approval of new/changed files |
| Factory | Approved plan → build → fixed checks → independent security role → owner acceptance; capped repair drafts | No endless repair loop, automatic publishing/merge/deployment or issue mutations |
| Verification | Captured command/status/output/count evidence and Git snapshot binding; out-of-scope changed-path gate | Model security review is advice, not a proof; only two fixed check profiles |
| Operations | SQLite/WAL, single runner, ownership fencing, stop/cancel/watchdog, explicit migration/recovery | Single-user/single-host; no sandbox provisioning, supervisor installation or distributed leases |
| Cost | No idle model calls; bounded concurrency, attempts, wall time, bytes and cumulative reservations | Not a hard bill guarantee or verified subscription quota meter |

## Installation and integration

```bash
bash install.sh                       # ~/.claude: /delegate + its four agents
bash install.sh --client codex         # ~/.agents/skills/superagent
# Optional alternate client root, with conflict checks and explicit replacement:
bash install.sh --client codex --dest /absolute/client-root
```

The default installer still manages the same Claude skill and four agent files.
The skill now includes a **passive, self-contained** runtime and one exact helper
entrypoint. Codex installation is explicit and manages only its superagent skill.
Neither installs a service, starts a worker, changes global CLI settings, reads
credentials or logs in. Existing conflict/backup/rollback behavior is preserved.
A changed installed payload requires explicit `--replace`; inspect its backup.

Use the bundled helper from any project, not `python -m superagent` from an
untrusted project directory. The launcher uses an isolated, no-bytecode Python
process and an absolute bundled package path, so cwd/PYTHONPATH cannot substitute
a fake runtime. Installed payloads keep working after the source checkout moves.

```bash
# Claude installation:
SA="$HOME/.claude/skills/delegate/scripts/superagent.sh"
# Or Codex installation:
SA="$HOME/.agents/skills/superagent/scripts/superagent.sh"
STATE=/absolute/private-superagent-state
bash "$SA" --state "$STATE" init \
  --workspace-root /absolute/agent-workspaces --repository owner/project \
  --workers 4 --budget-cents 1000
bash "$SA" --state "$STATE" status
```

For checkout-only development, `python3 -m superagent` works **from this trusted
repository**, and both project skills have a working helper. The installer is
not required for the offline demo.

### The AI lead's actual bridge

In Claude use `/delegate`; in Codex use the `superagent` skill. The lead:

1. Reads the backlog and current project, proposes eligible IDs, acceptance
   criteria, risk assessments and allowed profile routes. Plan-only stays planning.
2. Writes a trusted policy or task JSON with explicit scope and limits. It may
   use already-valid user approval; it must not fabricate approval from comments.
3. Calls `import-folder` / `create`, reviews the resulting drafts, then records
   matching permission with `approve-factory` / `approve`.
4. Starts the bounded runner, inspects `factory-status`, `tasks`, `events`,
   `graph` and `recall`, and handles held/failed outcomes. Strong security review
   follows tool checks; the owner/lead verifies the evidence before `accept`.
5. For repairs, calls `repair-draft` with the original build and failed result.
   It reviews/approves that new scoped draft explicitly and schedules fresh checks
   and security review afterward. There is no autoaccept or automatic repair loop.

This is a **hybrid AI planner plus deterministic controller**, not a fixed script
pretending to reason. Profiles/risk/overrides are proposed by the lead and approved
locally. The controller enforces the frozen proposal. Existing ordinary `/delegate`
rules remain: unknown usage does not block normal parallel work, prefer 3–6 useful
independent workers, preserve explicit Opus requirements, honor matching per-job
Codex approval at observed ≥70%, and keep interactive Codex human-controlled.
The new runtime does not discover quota or activate that threshold itself.

## Folder-backed factory

The board can later export one JSON task per file into an existing flat folder.
See [sample item](../examples/superagent/backlog/item-1.json) and
[policy template](../examples/superagent/factory-policy.json). Source files are
never edited; progress and evidence live in the private database.

```json
{
  "id": "item-1",
  "title": "Add pagination coverage",
  "description": "Implement the agreed pagination behavior within the approved paths.",
  "acceptance": "Cover empty, first and last pages; preserve existing API behavior.",
  "dependencies": [],
  "ready": true
}
```

The schema is strict: these six fields only. `ready` is an eligibility hint, not
permission. No models, shell commands, workspace paths, approval, budget or risk
claims are accepted from task files. A malformed/partial export fails closed and
can be rechecked. Limits: 128 folder entries, 32 KiB per JSON, 1 MiB aggregate;
no symlinks, subdirectories, special files, duplicate IDs, missing dependencies
or cycles. Actual reads are bounded, not merely initial file sizes.

The **trusted policy**, stored separately from the export, selects at most 16 IDs
(default 4), their full dependency closure, one dedicated workspace each, allowed
paths, fixed checks, model catalog, stage routes, operator risk and limits.

- Planning and security must use an operator-designated `strong` profile.
- Routine, explicitly low-risk builds/test writing may use a `routine` profile.
  Unknown/high-risk work inherits the strong planning profile.
- Explicit per-item overrides are honored within the role/risk floor; conflicts
  fail before approval. Backlog labels cannot downgrade risk. A tier is an owner
  assertion, not an automatically verified claim about model quality or price.
- Running tests uses deterministic tools, **no LLM just to execute them**.
- No automatic provider/model upgrade, fallback or resumed-session model switch.
  Use a fresh scoped task/policy for a newly approved escalation.
- Use exact operator-approved model IDs appropriate to the account. `best`,
  `default`, `auto` and `fable` are rejected for live routes. Availability,
  entitlement and effective model remain unknown unless actually reported.

```bash
bash "$SA" --state "$STATE" folder-manifest /absolute/backlog
# Edit/review policy paths, IDs, models, limits and optional approved_hashes.
bash "$SA" --state "$STATE" import-folder /absolute/policy.json
bash "$SA" --state "$STATE" factory-status batch-1
bash "$SA" --state "$STATE" approve-factory batch-1 \
  --evidence 'User approved these exact items, revisions, profiles, paths and limits'
bash "$SA" --state "$STATE" run --once   # mock tasks only
bash "$SA" --state "$STATE" factory-status batch-1
```

Each item has a stable source key and content hash. Duplicate imports are no-ops.
Changed content conflicts rather than rewriting an existing approved task/result.
A new revision needs a reviewed new item ID (or a deliberately new backlog identity
and policy), not editing approvals in the database. Policy IDs are immutable too.
Dependencies between items require the predecessor's final security stage to be
**accepted**. Within an approved item, plan/build/check/security stages follow
completed predecessors. A failure visibly blocks downstream work. A completed
security stage only means there is a review report; it does not mean “secure.”

### Keep checking the approved folder without idle model use

Put the reviewed `id → content_hash` values from `folder-manifest` into the trusted
policy's `approved_hashes`. The keys must exactly match `selected_ids` for automatic
admission. Then an explicitly authorized foreground watcher can run:

```bash
bash "$SA" --state "$STATE" run --watch-policy /absolute/policy.json \
  --poll-seconds 30 --approve-matching \
  --approval-evidence 'Standing approval only for this fixed ID/revision manifest and policy'
```

Polling is deterministic (minimum 5 seconds), persists changed status only, and
makes zero model calls for empty/waiting/deduplicated work. Without
`--approve-matching`, it imports drafts only. Unknown IDs appear pending;
changed selected revisions hold intake. Neither can inherit approval. The policy
is loaded once for this service run; restart explicitly to change reviewed policy.
The default one-hour service deadline still applies. This is not a silently
installed 24/7 service or permission to start all future backlog items.

### Evidence and protection of existing work

Live writer/factory work requires an already-prepared, clean dedicated Git
worktree on `superagent/*`, never main/master/trunk, detached HEAD or an existing
dirty checkout. Preparation is deliberate: the runtime never creates branches,
resets, cleans, overwrites old worktrees or auto-merges. Use the same `project`
key for all worktrees of one project; overlapping writers/checks are serialized.

Approval, stage start, result and acceptance are bound to Git fingerprints.
External changes require re-review. Before every Git inspection, the runtime and
legacy handoff/review helpers reject configured clean/process/smudge filters:
status/diff can otherwise execute them even when external diff and textconv are
disabled. System Git is used with hooks/monitors disabled, lazy object fetching
disabled and all transport protocols denied. Missing objects/configuration errors
fail closed. Repositories requiring executable filters need a separately reviewed
safe workflow; the controller never removes their settings to proceed.
Protected readers/checks must finish with the same snapshot they started with. Writer completion rejects tracked, deleted,
renamed or untracked changed paths outside the approved scope. This is an
**after-the-fact gate**, not prevention or rollback. Ignored files and submodules (including gitlink changes) are excluded from
these inspection/fingerprint guarantees; hostile same-user processes and changes
made then reverted need external isolation. Do not promise that edits cannot happen.

Security workers receive the complete bounded selected item, predecessor evidence
and a hardened Git HEAD/status/diff artifact. Large context fails before launch
rather than silently dropping acceptance criteria. Untracked contents must be
inspected by file tools. The packet records source revision, policy hash, routes,
attempt/result refs and workspace fingerprints. Human acceptance remains required;
there is no automatically opened target-project PR. Review and publish separately.

```bash
bash "$SA" --state "$STATE" repair-draft BUILD_TASK \
  --from-result CHECK_OR_REVIEW_TASK --new-id repair-1 --goal 'Fix within the original scope'
# At most two repair drafts per original build. Both still need matching approval.
```

## Continuing tickets and context recall

For direct tasks, copy [task.json](../examples/superagent/task.json), keep mock mode
first and add the desired immutable continuation mandate:

```json
{
  "continuation": "subscribed",
  "subject": "issue:7",
  "subscriptions": ["issue_comment"],
  "max_attempts": 4,
  "total_budget_cents": 400,
  "lifetime_seconds": 3600
}
```

`none` (default) preserves one-shot semantics; `owner` wakes only on trusted local
instructions; `subscribed` also wakes on an explicitly scoped event subject and
kind. GitHub issue/PR subjects are derived from the payload's number/type for the
configured repository, not from free-text commands. These offline claims are not
verified identities or webhook signatures. Events arriving after task creation
are delivered; there is no automatic historical backfill.

```bash
bash "$SA" --state "$STATE" create /absolute/task.json
bash "$SA" --state "$STATE" approve TICKET --evidence 'Approved bounded continuing mandate'
bash "$SA" --state "$STATE" run --once
bash "$SA" --state "$STATE" instruct TICKET --message-id owner-message-001 \
  --text 'Clarification within the original paths, provider, permissions and budget'
bash "$SA" --state "$STATE" ingest-github /absolute/event.json \
  --kind issue_comment --delivery-id delivery-001
bash "$SA" --state "$STATE" graph TICKET
bash "$SA" --state "$STATE" events --task TICKET
```

The durable inbox batches pending input at claim time; input arriving during a
turn belongs to the next turn. Duplicate IDs dedupe; changed bodies conflict.
Owner instructions are delivered in full or the prompt fails its cap. They cannot
change the immutable task. `blocked`/invalid reports enter `held`, released only
by a new trusted instruction, not ordinary events. Accepted/stopped results never
reopen. Use a new task for post-acceptance follow-up.

An ongoing worker returns a bounded JSON report in its final answer:
`{"status":"waiting|ready|blocked|recall","summary":"...","recall":["SHA256"]}`.
Recall references must belong to this task's delivered evidence/predecessor graph.
A hash is not authority. Controller recall is limited to 4 refs/16 KiB per round,
8 total refs, duplicate suppression, and the same attempt/time/budget caps. A
recall response is still untrusted content. Owner `recall REF` is a local inspection
command, not an unrestricted worker capability. `previous_task` supplies explicitly
linked predecessor output; it does not inherit approval or a provider session.

Persistent tasks bind exact provider session UUID, workspace, model, mode and
paths. One task owns a session; no `--last`, name-based lookup or fresh-session
fallback on missing/mismatched IDs. First Claude sessions are preassigned IDs;
subsequent calls use exact `--resume`; Codex uses exact `exec resume ID`. Required
permission flags are reapplied each turn. Model completion and owner acceptance
remain separate. Provider session persistence means provider-local transcripts
now exist for continuing tasks; retention is separate from controller artifacts.

## Live execution is a separate deployment step

No live provider or container integration was validated for this release. First
review the actual folder/project, model catalog, account settings, check image and
budget with the owner. Provision and verify an isolated worker host, scoped mounts,
egress restrictions and independent billing controls. Keep controller state outside
worker-writable mounts. **Worktrees are not security isolation.** Same-UID processes
can attack each other; flags and assertions are not proof of containment.

```bash
# Only after the scope, account, environment and external controls are authorized:
bash "$SA" --state "$STATE" run --once \
  --live --isolated-host --external-budget-guard
```

The runner probes current CLI capabilities and subscription authentication before
each launch/resume (capabilities are cached, account route is rechecked). Claude
must report `claude.ai`; Codex must report ChatGPT login. Unknown/API routes and
conflicting API/custom-provider/model environment variables fail closed without
reading their values. No login, secret extraction, credential export, new account,
automatic install or API fallback exists. **Subscription login does not prove
extra usage/credits are disabled or that a model is included.** Review account
billing controls yourself; no guarantee of zero extra charges is made.

### Provider contracts (official references checked 2026-11-03)

- Claude uses `-p --output-format json`, `--safe-mode --restricted`, `dontAsk`, no
  permission prompts, explicit model, max turns and estimated budget. Per-launch
  settings disable content-based switching and fallback chains, and restrict the
  available model list to the requested profile. Managed policy and actual model
  identity still require verification; no live guarantee is inferred. Only
  Read/Grep/Glob are enabled, plus Edit/Write for approved writers. No Bash/Agent,
  recursive agents or ordinary plugins/MCP are granted. Safe mode preserves normal
  authentication, unlike API-oriented `--bare`. Managed-policy hooks can still run:
  audit the host. One-shot tasks disable session persistence; continuing tasks own
  exact sessions. See [CLI reference](https://code.claude.com/docs/en/cli-reference),
  [headless](https://code.claude.com/docs/en/headless), and
  [models and usage credits](https://code.claude.com/docs/en/model-config).
- Codex uses `exec --json`, `--ignore-user-config`, read-only or approved
  workspace-write, approval policy never, command-network false and web search
  disabled; one-shot tasks add `--ephemeral`. Resume keeps parent policy flags
  before the `resume` subcommand and names the exact session. No bypass or fallback.
  Command sandbox networking is not a global provider/auth/integration kill switch;
  managed/project configuration still needs audit. See
  [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode) and
  [security](https://learn.chatgpt.com/docs/agent-approvals-security).

Structured terminal success is required, not merely exit 0. Missing/error/truncated
outputs fail; activity after a terminal Codex event is refused. Requested models
and raw provider usage are recorded separately from verified identity (`unknown`
when unavailable). Tokens are not quota. No paid model discovery runs are used.

### Deterministic check execution

`git-diff-check` runs hardened fixed Git whitespace checking without a model; it is
not a security scanner. `python-unittest` executes arbitrary project code only in
an approved **preinstalled digest-pinned Docker image**, never auto-pulled. The
fixed local daemon, trusted Docker executable, exact read-only workspace mount,
network none, read-only root, non-root operator UID/GID, dropped capabilities,
no-new-privileges, CPU/memory/PID caps and bounded `/tmp` are explicit. No host home,
controller state, socket or credential mounts are passed. `/tmp` permits temporary
executables because tests may need them; source stays read-only and 0600 source
files remain readable by the same non-root UID. No chmod of user work occurs.

A fixed Python entrypoint discovers non-package `tests/`, fails zero discovery,
and records discovered/run/failure/error counts plus exit/output. Tests requiring
writes into the checkout, network, extra services or another framework need a
separately designed supported profile; do not claim they passed. Tests can lie,
skip or lack coverage: execution evidence is not a proof of correctness/security.
A malicious approved image also remains a trust risk. No Docker access is installed
or permission accepted for you. Current Docker contract tests are mocked, not a
successful real container execution of this repository.

Cancellation/timeout targets the exact attempt process group and labeled container.
Uncertain daemon cleanup stops new dispatch and requires recovery; no broad
container prune or unrelated-container kill. Model CLI workers still require their
own external isolation; this check container is not a sandbox for the whole service.

## Cost, lifecycle, recovery and retention

Hard local bounds are workers (default 4, configurable 1–6), queue, attempt count,
per-turn and ticket lifetime, service deadline, prompt/log/event bytes. The global
budget/start reservations persist for the **whole state lifetime**, including
restarts, which is stricter than a reset-each-day allowance. Per-ticket cumulative
budgets and max attempts survive resume. No automatic midnight resets or refunds.

`budget_cents` reserves a declared envelope per attempt, not a measured bill.
Claude's estimated `--max-budget-usd` can overshoot and resets per invocation;
resumed cumulative provider totals must not be summed as new charges. Codex token
usage has no verified hard dollar cap here. Extra credits can cost money without
another prompt; there is no `best`/Fable upgrade. External controls are required.
Empty/waiting backlog has zero model calls; no expensive model is used to poll.

State transitions are draft → queued → running → completed → accepted, with
waiting/held for continuing tickets, and blocked/failed/cancelled/interrupted
outcomes. Cancelled/accepted tasks are terminal. Each claim persists its unique
attempt, owner and input boundary before launching. Late completions cannot defeat
cancellation. Cancellation is not rollback; detached escaped children need host
containment. `stop` interrupts active work and preserves queued work.

```bash
bash "$SA" --state "$STATE" cancel TICKET
bash "$SA" --state "$STATE" stop
# After stopping ALL old workers/containers and inspecting possible effects:
bash "$SA" --state "$STATE" recover --ack-workers-stopped \
  --evidence 'Old isolated workers stopped; source changes and effects inspected'
```

Unclean startup marks prior attempts interrupted, input uncertain, and refuses all
new dispatch until explicit recovery. No PID guessing or automatic paid replay.
Recovery clears the global barrier, not terminal tasks. Create a fresh reviewed
task with `previous_task` if appropriate. Exactly-once external effects cannot be
promised after a crash. Heartbeat is every 5 seconds; idle polling is throttled.

v0.1 state is never silently upgraded:

```bash
bash "$SA" --state "$STATE" migrate --ack-workers-stopped \
  --evidence 'All v0.1 workers stopped and their changes inspected'
```

Migration takes a private consistent backup, normalizes old tasks to one-shot,
preserves reservations and marks old active work interrupted. The transaction
rolls back on errors. Do not manually edit the schema or reset budgets.

Defaults: 64 queued tasks, 1,024 stored tasks, 2,048 events, 64 MiB artifact bodies,
64 KiB/event, 256 KiB/prompt, 1 MiB provider output, 64 total attempts, 300-second
turn timeout, 1-hour task and service lifetimes. The library `Limits` constructor
supports explicitly reviewed bounded overrides; not every field is a CLI flag.
Artifact bytes exclude SQLite/WAL overhead, so use a host disk quota too.

State is private 0700 with 0600 files, outside the workspace root; no symlinks.
This is not encryption or multi-user authentication. Approval evidence asserts
prior permission; the local CLI cannot authenticate that assertion. Keep secrets
out of prompts/policy. Archive the whole stopped state directory including WAL to
private storage before a deliberately newly authorized state/budget. Retention is
manual, including private migration backups and provider-local persistent sessions.
Never export personal CLI auth to public CI.

## Pros and trade-offs

**Pros:** a real reusable entrypoint for both leads; durable work and scoped context;
no idle LLM polling; explicit specialist/model routes; finite workflows and cost
reservations; independent check/review evidence; protects old work by failing
closed rather than cleaning it; small standard-library controller.

**Trade-offs:** strict setup and limited check profiles; operational state and manual
recovery; CLI/version coupling; isolation and billing controls remain external;
strong reviews still use quota; fixed polling/turn boundaries rather than realtime
streams; new backlog revisions and repairs need reviewed authority. Simpler tasks
are better served directly by the original skill.

Next deployment milestone is a supervised small real-project pilot after the owner
supplies the folder, approved subscriptions/models, non-root isolated host and check
image. Only then validate actual CLI resume/sandbox behavior, container compatibility,
usage and failure recovery. Board integrations, richer check/scanner profiles,
24/7 hosting, remote workers and an approved PR publisher are separate future work.
