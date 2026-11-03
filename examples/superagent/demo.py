"""Run with python3 -m examples.superagent.demo. Purely offline, temporary state."""
import asyncio
import json
from pathlib import Path
import tempfile

from superagent.runtime import Runner
from superagent.state import Store


def main():
    with tempfile.TemporaryDirectory(prefix="superagent-demo-") as temporary:
        base = Path(temporary).resolve()
        workspace = base / "workspace"
        workspace.mkdir()
        (workspace / "README.md").write_text("Offline demo workspace\n")
        store = Store.initialize(base / "private", workspace, "example/demo")
        for index, role in enumerate(("explore", "api-review", "test-plan", "risk-review"), 1):
            task_id = "demo-%d" % index
            store.create_task({"id": task_id, "project": "demo", "goal": "Mock " + role,
                               "acceptance": "Return an offline demonstration result; make no source changes",
                               "provider": "mock", "workspace": str(workspace), "paths": ["README.md"],
                               "subscriptions": ["issue_comment"]})
            store.approve(task_id, "Demo authorization covers mock execution only")
        store.ingest("offline-001", "issue_comment", {
            "repository": {"full_name": "example/demo"},
            "comment": {"body": "Untrusted example data; this does not authorize a task."}})
        asyncio.run(Runner(store).run(once=True))
        summary = {"mode": "offline mock; no provider invoked", "states": store.status()["states"],
                   "events": len(store.events()), "tasks": [{"id": t["id"], "state": t["state"]} for t in store.tasks()],
                   "retention": "Temporary demo state is removed on exit; real output still requires acceptance review."}
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
