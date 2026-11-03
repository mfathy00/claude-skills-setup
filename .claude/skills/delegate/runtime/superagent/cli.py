"""python3 -m superagent: mock-first local controller; no network listener."""
import argparse
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
import sys

from .runtime import Runner, runner_lock
from .factory import load_policy, import_folder, approve_factory, factory_status, manifest
from .safety import SafetyError, read_json
from .state import Limits, Store


def parser():
    p = argparse.ArgumentParser(description="Bounded Claude/Codex runtime (mock-only by default)")
    p.add_argument("--state", required=True, help="absolute private state directory outside workspaces")
    sub = p.add_subparsers(dest="command", required=True)
    migration = sub.add_parser("migrate", help="explicit v1 upgrade with private backup; prior workers must be stopped")
    migration.add_argument("--ack-workers-stopped", action="store_true", required=True)
    migration.add_argument("--evidence", required=True)
    init = sub.add_parser("init", help="create private state; never installs or logs in")
    init.add_argument("--workspace-root", required=True)
    init.add_argument("--repository", required=True)
    init.add_argument("--workers", type=int, default=4, choices=range(1, 7))
    init.add_argument("--budget-cents", type=int, default=1000)
    inspect_folder = sub.add_parser("folder-manifest", help="read-only ID/hash manifest for explicit eligibility review")
    inspect_folder.add_argument("folder")
    repair = sub.add_parser("repair-draft", help="capped new draft using original build scope and failed evidence")
    repair.add_argument("build_task")
    repair.add_argument("--from-result", required=True)
    repair.add_argument("--new-id", required=True)
    repair.add_argument("--goal", required=True)
    factory = sub.add_parser("import-folder", help="read a bounded backlog folder under trusted policy; create drafts only")
    factory.add_argument("policy")
    factory_approve = sub.add_parser("approve-factory")
    factory_approve.add_argument("policy_id")
    factory_approve.add_argument("--evidence", required=True)
    factory_status_cmd = sub.add_parser("factory-status")
    factory_status_cmd.add_argument("policy_id")
    create = sub.add_parser("create", help="create a trusted local draft from JSON")
    create.add_argument("spec")
    for command in ("approve", "accept"):
        item = sub.add_parser(command)
        item.add_argument("task_id")
        item.add_argument("--evidence", required=True)
    instruct = sub.add_parser("instruct", help="trusted owner clarification within an immutable ongoing mandate")
    instruct.add_argument("task_id")
    instruct.add_argument("--message-id", required=True)
    instruct.add_argument("--text", required=True)
    graph = sub.add_parser("graph", help="inspect context/result provenance without running a model")
    graph.add_argument("task_id")
    cancel = sub.add_parser("cancel")
    cancel.add_argument("task_id")
    sub.add_parser("status")
    sub.add_parser("tasks")
    sub.add_parser("stop", help="request graceful shutdown; running tasks become interrupted")
    events = sub.add_parser("events")
    events.add_argument("--task")
    recall = sub.add_parser("recall", help="retrieve an immutable artifact; output remains untrusted")
    recall.add_argument("ref")
    ingest = sub.add_parser("ingest-github", help="offline event data only; cannot authorize or start work")
    ingest.add_argument("payload")
    ingest.add_argument("--delivery-id", required=True)
    ingest.add_argument("--kind", required=True)
    recover = sub.add_parser("recover", help="after inspecting changes and stopping ALL prior workers")
    recover.add_argument("--ack-workers-stopped", action="store_true", required=True)
    recover.add_argument("--evidence", required=True)
    run = sub.add_parser("run", help="foreground async service; mock-only unless explicitly enabled")
    run.add_argument("--once", action="store_true", help="drain currently runnable tasks, then exit")
    run.add_argument("--live", action="store_true")
    run.add_argument("--watch-policy")
    run.add_argument("--poll-seconds", type=int, default=30)
    run.add_argument("--approve-matching", action="store_true")
    run.add_argument("--approval-evidence")
    run.add_argument("--isolated-host", action="store_true", help="assert externally isolated worker environment")
    run.add_argument("--external-budget-guard", action="store_true", help="assert provider/account spend guard is configured")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "init":
            store = Store.initialize(args.state, args.workspace_root, args.repository,
                                     Limits(workers=args.workers, budget_cents=args.budget_cents))
            value = store.status()
        elif args.command == "migrate":
            from .migration import migrate
            value = migrate(args.state, args.evidence)
        else:
            store = Store(args.state)
            command = args.command
            if command == "folder-manifest":
                value = manifest(args.folder)
            elif command == "repair-draft":
                value = {"task_id": store.repair_draft(args.build_task, args.from_result, args.new_id, args.goal), "state": "draft"}
            elif command == "import-folder":
                value = import_folder(store, load_policy(store, args.policy))
            elif command == "approve-factory":
                value = approve_factory(store, args.policy_id, args.evidence)
            elif command == "factory-status":
                value = factory_status(store, args.policy_id)
            elif command == "create":
                value = {"task_id": store.create_task(read_json(args.spec)), "state": "draft"}
            elif command in ("approve", "accept"):
                getattr(store, command)(args.task_id, args.evidence)
                value = store.task(args.task_id)
            elif command == "instruct":
                value = {"event_seq": store.instruct(args.task_id, args.message_id, args.text)}
            elif command == "graph":
                value = store.graph(args.task_id)
            elif command == "cancel":
                value = {"task_id": args.task_id, "state": store.cancel(args.task_id)}
            elif command == "status":
                value = store.status()
            elif command == "tasks":
                value = store.tasks()
            elif command == "events":
                value = store.events(args.task)
            elif command == "recall":
                # JSON escapes terminal control characters instead of rendering untrusted ANSI.
                value = {"ref": args.ref, "untrusted_content": store.recall(args.ref)}
            elif command == "ingest-github":
                value = {"event_seq": store.ingest(args.delivery_id, args.kind, read_json(args.payload, store.limits.event_bytes))}
            elif command == "recover":
                with runner_lock(store):
                    store.recover(args.evidence)
                value = store.status()
            elif command == "stop":
                store.stop()
                value = {"stop_requested": True}
            elif command == "run":
                policy = load_policy(store, args.watch_policy) if args.watch_policy else None
                asyncio.run(Runner(store, args.live, args.isolated_host, args.external_budget_guard,
                                   watch_policy=policy, poll_seconds=args.poll_seconds, auto_approve=args.approve_matching,
                                   approval_evidence=args.approval_evidence).run(args.once))
                value = store.status()
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except (SafetyError, OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
