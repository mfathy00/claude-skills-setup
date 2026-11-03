# Bounded super-agent runtime · v0.1

**A small, local service alongside the skills—not a prompt pretending to be a
production autonomous system.** It can coordinate approved Claude and Codex
workers, remember tasks/events across restarts, and stop work predictably. It
starts in **mock-only mode**. No packages, upstream prototype, credentials,
webhooks, background login service, or global settings are installed.

## What you get

| Shipped in this MVP | Deliberately not shipped |
|---|---|
| Python 3.9+ standard library; SQLite/WAL durable state | Distributed control plane / multi-host worker protocol |
| Fixed non-executing subscription router | LLM router that invents or authorizes tasks |
| Explicit trusted task creation + approval evidence | Trusting GitHub actors/comments as authorization |
| Four parallel workers by default; configurable 1–6 | Unlimited agents, recursive spawning, automatic decomposition |
| Async foreground service, cancellation, stop, watchdog | System daemon installation or unattended deployment |
| One-shot Claude and Codex CLI adapters | Automatic paid retries, implicit resume, model fallback |
| Offline GitHub event intake and pass-through inbox | Public webhook endpoint, polling credentials, posting comments |
| Inline previews, immutable SHA-256 spill/recall artifacts | Automatic model-driven recall, streaming mid-turn event injection |
| Attempt ownership, conflict prevention, acceptance gate | Automatic merge, acceptance inferred from exit code |
| Wall-clock/output/queue/start caps and spend reservations | A guaranteed dollar ceiling or inferred subscription usage |

### Where this fits

```text
Claude /delegate or Codex lead (trusted plan + existing approval)
                         │ explicit local task JSON
                         ▼
                   draft → approved queue
                         │ bounded admission + ownership
offline GitHub JSON → router → durable inbox → attempt snapshot
                         │                    │
                         │             async worker (mock / CLI)
                         │                    │
                         └────────── result artifact → human/lead review → accepted
```

The router only matches the event kind against predeclared subscriptions for the
configured repository. It never runs a model, parses `/commands`, trusts a sender,
changes provider, grants approval, or creates tasks. Duplicate delivery IDs are
idempotent; reusing an ID with different kind/content is an error. Subscriptions
receive events arriving **after task creation**; no silent historical backfill.
Events arriving after an attempt starts remain in its inbox, not in that running
prompt. Inspect them and create a new explicit continuation task if needed.

This is inspired by the separation of routing, state, worker execution and
context references described in the [DeepSeek research prototype](https://github.com/deepseek-ai/dsh-superagent-prototype)
and its [architecture notes](https://github.com/deepseek-ai/dsh-superagent-prototype/blob/main/docs/007-architecture.md).
No upstream source was installed, run or copied, and its unrestricted execution
choices are **not** reproduced. This project does not claim prototype or
production feature parity.

## Try it safely in one command

From this repository checkout:

```bash
python3 -m examples.superagent.demo
bash tests/run.sh
```

The demo creates a temporary workspace/private database, routes one fake GitHub
comment, and runs four **mock workers**. It invokes no Claude/Codex executable,
uses no network, changes no project source, and removes its temporary files. Tests
also use only mocks/fake executables; see [verification](#verification).

Supported hosts: Linux/macOS; Windows through **WSL only**, with Python and CLIs
inside WSL. The controller uses POSIX process groups and `flock`; network-mounted
SQLite state, multiple hosts and native Windows are not supported.

## Set up persistent local state

Use a dedicated parent for your authorized workspaces, and put state **outside**
that tree. Both paths must already have real, non-symlink parents. On macOS,
`pwd -P` / Python's `Path.resolve()` canonicalizes aliases such as `/var` →
`/private/var`. The runtime refuses symlink paths rather than following them.

```bash
# Run from the runtime repository; replace these absolute paths for your machine.
python3 -m superagent --state /home/me/.superagent-project init \
  --workspace-root /home/me/agent-workspaces \
  --repository owner/project --workers 4 --budget-cents 1000
```

Initialization creates private 0700 state and a 0600 database. It refuses an
existing database, insecure state permissions, symlinks and a state/workspace
overlap. It does not create worktrees, install CLIs, inspect credentials, log in,
or edit your profiles. `install.sh` still installs **only** the original Claude
skill and four agents; this optional Python runtime runs from its own checkout.

### 1. Write a trusted task

Copy [the example](../examples/superagent/task.json) to an absolute file path and
replace the workspace with an existing authorized checkout below your configured
root. Start with `"provider": "mock"`.

```json
{
  "id": "api-review-1",
  "project": "my-project",
  "goal": "Review pagination edge cases without changing files",
  "acceptance": "Report findings with file references and proposed tests",
  "provider": "mock",
  "model": "default",
  "workspace": "/home/me/agent-workspaces/project",
  "mode": "read-only",
  "paths": ["src/api", "tests"],
  "timeout_seconds": 300,
  "budget_cents": 100,
  "max_turns": 12,
  "dependencies": [],
  "subscriptions": ["issue_comment"]
}
```

The task spec is **trusted local instruction**, not an event payload. Never feed
an untrusted attachment/comment directly to `create`, `approve`, or `recover`.
Unknown fields are rejected. Task IDs are immutable/idempotent; changed scope,
provider, model, mode or limits require a **new ID and matching authorization**.
Task text and approval evidence must not contain secrets.

- `paths` are explicit relative scope instructions, not filesystem permissions.
  Traversal, symlinks and direct Git/agent-configuration paths are refused.
- `project` is a consistent logical conflict key: use the **same value for all
  worktrees of one project**. Do not rename it to bypass a conflict.
- Writers sharing/overlapping a checkout are serialized, even for different
  paths. Separate checkouts/worktrees can run together only with nonoverlapping
  logical scopes. Readers can run in parallel. External editors/processes and
  other state databases are **not** coordinated; keep one controller per project.
- Dependencies must refer to existing tasks; they run only after those tasks
  are explicitly `accepted`, not merely `completed`. A failed/cancelled parent
  leaves its dependents queued for an operator decision.
- `previous_task` may identify an earlier task for an explicit continuation.
  It records lineage, not automatic resume/retry or inherited approval. Neither
  dependency results nor previous-task outputs are automatically injected; review
  and include any required context explicitly. Provider session IDs are diagnostic
  metadata only because ephemeral/no-persistence mode intentionally disables resume.

### 2. Record existing authorization; do not ask twice

```bash
python3 -m superagent --state /home/me/.superagent-project create /absolute/task.json
python3 -m superagent --state /home/me/.superagent-project approve api-review-1 \
  --evidence 'User approved this scope/provider/read-only mode and cost envelope'
python3 -m superagent --state /home/me/.superagent-project run --once
python3 -m superagent --state /home/me/.superagent-project tasks
```

The approval command asserts the caller already has authorization; it is **not
an authentication system**. The trusted lead may record valid prior approval
without repeatedly asking. Plan-only never authorizes these execution steps.
`run --once` drains currently runnable work and exits; waiting dependencies,
live tasks in mock mode and blocked tasks remain visible in `tasks`/`status`.
An exit code of zero means the controller invocation succeeded, **not that every
task passed**. Inspect each task's state and output.

Use `run` without `--once` for a foreground async service that accepts work from
other terminal invocations. It stops after the configured service deadline
(default one hour), Ctrl-C/SIGTERM or `stop`. This repo does not install a daemon.

### 3. Optional offline GitHub events

```bash
python3 -m superagent --state /home/me/.superagent-project ingest-github \
  /absolute/event.json --delivery-id offline-example-001 --kind issue_comment
python3 -m superagent --state /home/me/.superagent-project events --task api-review-1
```

A payload must include `{"repository":{"full_name":"owner/project"}}` matching
initialization. Delivery IDs are caller-supplied deduplication keys, not verified
webhook signatures. **This is offline ingestion, not authenticated GitHub
integration.** Labels, author names, approval-like text and issue commands grant
no authority. Never post outputs automatically.

Event bodies are stored once as immutable content-addressed artifacts. Small
content is inline; larger content gets a bounded preview plus SHA-256 reference.
`recall REF` returns JSON-escaped untrusted content, suitable for controller
inspection without interpreting terminal escape sequences. Attempt records keep
the exact spec/event-reference snapshot. Late events do not alter it. Automatic
worker recall and live steering are future features; include needed reviewed
context in a new bounded task rather than silently rerunning a paid invocation.

### 4. Review, accept, cancel, stop

```bash
python3 -m superagent --state /home/me/.superagent-project recall RESULT_SHA256
python3 -m superagent --state /home/me/.superagent-project accept api-review-1 \
  --evidence 'Reviewed output and verified the stated acceptance checks'
python3 -m superagent --state /home/me/.superagent-project cancel OTHER_TASK_ID
python3 -m superagent --state /home/me/.superagent-project stop
```

`completed` means the mock or provider returned a usable terminal result;
`accepted` requires explicit verification evidence. Model output is not proof
that tests passed, permissions were respected, or the requested model was used.
Requested model and observed metadata stay distinct; actual model is `unknown`
unless defensibly exposed, and this runtime never infers quota from token usage.

Cancellation of queued work prevents dispatch. Active cancellation sends TERM
then KILL to the owned process group and records `cancelled`; a late completion
cannot overwrite cancellation. Stop/deadline interrupts active work, preserving
queued work. Any filesystem edits already made remain; cancellation is **not
rollback**. Detached workers or processes deliberately escaping their group need
host-level containment/cleanup; process groups are not a security sandbox.

## Enabling live workers (separate, explicit step)

**Do not run live work on a sensitive everyday host.** First provision and verify
an externally isolated sandbox/VM/container with scoped workspace mounts,
restricted egress, no unrelated secrets, provider-specific credentials and
independent billing/usage controls. Keep controller state outside worker-writable
mounts. Audit managed settings, installed clients and integrations. Worktrees
are change isolation, **not security isolation**. This runtime does not provision,
verify or secure that host for you, and cannot contain a hostile same-UID process.

Only after the task/provider/cost is authorized and that environment is ready:

```bash
python3 -m superagent --state /home/me/.superagent-project run --once \
  --live --isolated-host --external-budget-guard
```

The acknowledgements are attestations by the trusted caller, **not detection or
proof**. Missing either fails closed. Mock mode never dispatches a live task.
Live tasks also require `provider: claude` or `provider: codex` in their approved
spec. Existing local CLI authentication is used by the client; no credentials
are read, configured or stored by this controller. Authentication/configuration
and model requests can still involve network traffic.

### Adapter contracts

Verified against the official references on **2026-11-03**. The runtime probes
`--help` for required flags, fails closed when unsupported, and never falls back
to broader privileges. This is not a substitute for a supported-version matrix
or live sandbox validation. No live provider run was performed for this release.

- **Claude:** one-shot `-p --output-format json`, `--safe-mode --restricted`, explicit
  model (default `opus`), narrow `--tools Read,Grep,Glob` plus Edit/Write only for
  approved write mode, `dontAsk`, no permission prompts, no session persistence,
  max turns and estimated budget. `--tools` restricts tools; `--allowedTools`
  preapproves only that same restricted set. No shell, recursive agent, network
  tool, discovered skill/plugin/MCP or interactive prompt is enabled by this
  adapter. In particular, Claude workers cannot execute test commands here;
  assign authorized checks to Codex or a human separately. Restricted file tools
  confine work to working directories, not to each task's `paths` subset.
  Safe mode preserves normal existing CLI authentication, including supported
  subscription login; we intentionally do **not** use `--bare`, whose documented
  API-only authentication would silently change that expectation. Account access
  and billing remain the installed client's responsibility; neither subscription
  compatibility nor this flag combination has been live-tested here. Missing
  flags fail closed. Managed policy hooks may still execute and must be audited;
  these flags are not an OS sandbox. See [CLI reference](https://code.claude.com/docs/en/cli-reference) and
  [headless guidance](https://code.claude.com/docs/en/headless).
- **Codex:** one-shot `exec --json --ephemeral --ignore-user-config`, prompt on
  stdin, explicit `read-only` (default) or approved `workspace-write`, approval
  policy `never`, workspace command-network disabled and hosted search disabled.
  No bypass/full-access/automatic-approval flags, resume-latest or fallback model.
  User-config suppression is not proof that every managed/project integration is
  disabled. Sandbox command-network settings are **not** a global network kill
  switch for provider/auth traffic or every integration. Validate the isolated
  host. See [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode),
  [CLI reference](https://learn.chatgpt.com/docs/cli/reference) and
  [security guidance](https://learn.chatgpt.com/docs/agent-approvals-security).

The adapters require structured terminal success, reject missing/malformed/error
output, and preserve bounded evidence. They never silently retry. Existing
interactive Codex continuation remains available through `/delegate`'s original
handoff scripts; unattended runtime workers deliberately do **not** fabricate a
TTY or answer a person's security prompts.

### What the spend guard actually guarantees

`budget_cents` is a **reservation/admission envelope**, not a bill estimate API.
The scheduler transactionally reserves it once per attempt against a lifetime
state budget (default 1,000 cents), plus a start count cap. Reservations are
never automatically refunded, including failures or uncertain interruptions.
This prevents over-admission relative to the declared envelopes, not real-world
overspend. Mock attempts reserve too, so the same policy can be exercised offline.

Claude's `--max-budget-usd` uses a client-side estimate and can overshoot. Codex's
CLI does not provide an equivalent verified hard dollar ceiling here. Provider
cost/token fields are observations, **not subscription quota**. Therefore every
live run requires independently configured account/provider spending controls
and explicit acknowledgement. Dollar guarantees, billing reconciliation and
quota-triggered runtime switching are not claimed. Hard local bounds are workers,
queue, start count, wall-clock time and captured bytes.

## Recovery and retention

```text
draft → queued → running → completed → accepted
   │       │        ├── failed / interrupted
   └───────┴── cancelled (running first enters cancelling)
           └── blocked (admission/path checks)
```

SQLite transactions prevent double claims and task/event IDs prevent duplicate
intake. Each attempt has a unique ID and owner token; stale owners cannot finish
it. One POSIX lock owns scheduling/recovery for a state directory. Heartbeat and
durable dirty state support operator diagnosis; this is not distributed leases.

After an unclean runner exit, startup records prior active attempts as
`interrupted`, marks recovery required, and refuses **all new dispatch**. It does
not signal saved PIDs (which might have been reused), infer old workers stopped,
or replay uncertain paid work. First stop/tear down all prior workers on the
isolated host, inspect diffs/output and any external side effects, then:

```bash
python3 -m superagent --state /home/me/.superagent-project recover \
  --ack-workers-stopped --evidence 'Old sandbox stopped; changes and side effects inspected'
```

This clears the global recovery barrier, **not** terminal tasks. Create a fresh,
reviewed task with `previous_task` to retry/continue. A lost response might have
cost money or changed files; exactly-once external execution is not promised.

Defaults: 64 queued tasks, 1,024 stored tasks, 2,048 events, 64 MiB artifact bodies,
64 KiB per event, 1 MiB captured provider stdout+stderr, 64 attempts, 300-second
default task timeout (max 3,600), and 3,600-second service lifetime. Other limits
are explicit `Limits` library configuration at initialization; they are not
editable via untrusted event/task fields. The artifact cap counts content bytes,
not SQLite/index/WAL/filesystem overhead; use an external disk quota if needed.

Capacity failures stop admission; no automatic deletion or evasion by resetting
budgets. Stop the controller, verify no workers remain, then archive the **whole
private state directory** to protected storage before deliberately creating a
new state with a newly authorized budget. Never copy only a live SQLite main
file while ignoring its WAL. Retention is manual; there is no purge scheduler.
State includes prompts, comments, outputs, paths and approval evidence. Private
permissions and `.gitignore` are not encryption. Review/redact exports; never
commit state or disclose it to unrelated providers. Provider-side retention is
independent of local cleanup.

## Using it from Claude and Codex

The existing `/delegate` behavior remains intact: unknown usage does not block
parallel work; prefer 3–6 independent workers for sufficiently complex work;
hard Claude implementation requests `opus`; valid job-level auto-Codex consent
at an observed ≥70% does not need repeat consent; interactive Codex stays human
controlled. The lead—not this fixed router—observes usage and applies that policy.
To avoid breaking in-flight state, do not migrate existing handoffs into the new
SQLite state automatically.

- Claude: see the optional runtime note in `.claude/skills/delegate/SKILL.md`.
  Existing helper tool grants and installer behavior do not change.
- Codex: `.agents/skills/superagent/SKILL.md` is the project-local instruction
  bridge. Other projects can reference this checkout/docs explicitly; copying or
  globally installing it is a separate deliberate step, not performed here.
- Neither skill grants permissions or launches work solely because an event said
  to. Use prior matching job approval when available. Runtime approval evidence
  is a durable note, not proof that a human approved it.

## Pros, trade-offs and when not to use it

**Pros:** durable context instead of sprawling chat-only handoffs; provider-neutral
coordination; useful bounded parallelism; duplicate-event resistance; reproducible
mock tests; explicit review/cost boundaries; no additional service dependency.

**Trade-offs:** more operational state and task planning; static rather than smart
routing; CLI/version coupling; no distributed sandbox provisioning; manual recovery
and retention; monetary controls are partly external; extra review and isolated
host setup before live work. Strict conflict rules trade throughput for safety.

Use the original skill for tiny changes or interactive jobs. Use this runtime
when several independent, clearly scoped tracks benefit from durable coordination.
Do not use it as a public autonomous GitHub bot, on hostile multi-tenant hosts,
or for unsupervised production deployment. Next candidates—after sandbox/live
validation—are authenticated ingestion, a remote worker transport, richer recall,
observability, per-provider usage reconciliation and explicit session continuation.

## Verification

`bash tests/run.sh` runs existing handoff/install/policy tests plus mock-backed
runtime tests. Runtime coverage includes duplicate/conflicting deliveries,
immutable approvals, malicious comments, bounded recall, concurrent claims,
ownership, cancellation/late-completion races, restart barriers, lock exclusion,
limits/budget, path/symlink/permission checks, logical writer conflicts, dependency
acceptance, adapter argv/structured results, output flood, timeout, watchdog and
CLI flows. Fake executables prove controller plumbing, **not live model behavior
or host sandbox enforcement**. No paid calls or credentials are needed. CI runs
on Linux/macOS; WSL itself and real provider versions remain untested.
