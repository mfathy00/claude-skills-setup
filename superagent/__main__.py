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
from .safety import SafetyError, read_json
from .state import Limits, Store


def parser():
    p = argparse.ArgumentParser(description="Bounded Claude/Codex runtime (mock-only by default)")
    p.add_argument("--state", required=True, help="absolute private state directory outside workspaces")
    sub = p.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create private state; never installs or logs in")
    init.add_argument("--workspace-root", required=True)
    init.add_argument("--repository", required=True)
    init.add_argument("--workers", type=int, default=4, choices=range(1, 7))
    init.add_argument("--budget-cents", type=int, default=1000)
    create = sub.add_parser("create", help="create a trusted local draft from JSON")
    create.add_argument("spec")
    for command in ("approve", "accept"):
        item = sub.add_parser(command)
        item.add_argument("task_id")
        item.add_argument("--evidence", required=True)
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
        else:
            store = Store(args.state)
            command = args.command
            if command == "create":
                value = {"task_id": store.create_task(read_json(args.spec)), "state": "draft"}
            elif command in ("approve", "accept"):
                getattr(store, command)(args.task_id, args.evidence)
                value = store.task(args.task_id)
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
                asyncio.run(Runner(store, args.live, args.isolated_host, args.external_budget_guard).run(args.once))
                value = store.status()
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except (SafetyError, OSError, sqlite3.Error, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
