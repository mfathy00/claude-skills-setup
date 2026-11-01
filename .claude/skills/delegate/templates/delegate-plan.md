# Delegate plan

- Run ID:
- Goal:
- Complexity: /10
- Intent: plan-only | execute
- Authorization: exact user-approved scope, provider/mode, and any exclusions
- Usage: session=unknown weekly=unknown; source=unavailable; observed at=unknown
- Proposed mode: normal-claude | lean-claude | codex-led (unknown usage defaults to normal-claude)
- Written: ISO timestamp

## Acceptance criteria
- [ ] Concrete, verifiable outcome

## Workflow (ordered phases)
### Phase 1 —
- Depends on: none
- Allowed paths / exclusions:
- Parallel OK: yes/no; isolation and shared-file risks:
- Verification commands:
- Status:

## Agents
| ID | Role | Preferred/requested model | Verified actual (or unknown) | Phase | Parallel group | Provider | Allowed paths |
|----|------|---------------------------|-----------------------------|-------|----------------|----------|---------------|

## Model policy / availability
- Requested model is not proof of current runtime. Disclose unavailable models.

## Codex usage
- Auto-Codex at ≥70%: no (set yes only after explicit per-job user opt-in)
- Opt-in evidence / approved by user at: none
- Approved remaining scope / allowed paths / exclusions:
- Approved runtime: exec | interactive; sandbox: read-only | workspace-write
- Revoked or scope changed: no (if yes, obtain only the missing approval)
- Approved scope and mode (or pending):
- Track IDs:
- Handoff/results: .claude/delegate-runs/<run-id>/<track>/
- No duplicate writers; separate worktrees for concurrent write tracks.

## Risks / open questions
- Privacy, permissions, quota/model visibility, and blockers:

## Results
- Checks actually run and results:
- Unmet criteria / follow-up:
