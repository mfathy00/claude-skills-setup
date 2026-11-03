"""Single local scheduler; durable state is independent of in-memory execution."""
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
import signal
import time
import uuid

from .adapters import CLIAdapter, ChecksAdapter, MockAdapter, prompt_for
from .safety import SafetyError, private_file


@contextmanager
def runner_lock(store):
    path = store.directory / "runner.lock"
    fd = os.open(str(path), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_file(path)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SafetyError("another runner/recovery owns this state") from exc
        yield
    finally:
        os.close(fd)


class Runner:
    def __init__(self, store, live=False, isolated_host=False, external_budget_guard=False, adapters=None,
                 watch_policy=None, poll_seconds=30, auto_approve=False, approval_evidence=None):
        if live and not (isolated_host and external_budget_guard):
            raise SafetyError("live execution requires isolated-host and external-budget-guard acknowledgements")
        if type(poll_seconds) is not int or not 5 <= poll_seconds <= 3600:
            raise SafetyError("folder poll interval must be 5-3600 seconds")
        if auto_approve and (not watch_policy or not approval_evidence or set(watch_policy.get("approved_hashes", {})) != set(watch_policy["selected_ids"])):
            raise SafetyError("automatic watch admission requires a fixed ID/hash manifest and approval evidence")
        self.watch_policy = watch_policy
        self.poll_seconds = poll_seconds
        self.auto_approve = auto_approve
        self.approval_evidence = approval_evidence
        self.store = store
        self.live = live
        self.adapters = adapters or {"mock": MockAdapter(), "claude": CLIAdapter("claude"), "codex": CLIAdapter("codex"), "checks": ChecksAdapter()}
        self.owner = uuid.uuid4().hex
        self.shutdown = asyncio.Event()
        self.active = {}
        self.preflighted = set()
        self.uncertain = False

    async def execute(self, task):
        spec = json.loads(task["spec"])
        spec["_workspace_root"] = str(self.store.root)
        spec["_attempt"] = task["attempt"]
        spec["_deadline"] = task["created"] + spec["lifetime_seconds"]
        spec["_session_id"] = task.get("session_id")
        spec["_requested_session_id"] = task.get("requested_session_id")
        try:
            remaining = task["created"] + spec["lifetime_seconds"] - time.time()
            if remaining <= 0:
                self.store.finish(task["id"], self.owner, task["attempt"], "cancelled", "", "task lifetime expired")
                return
            spec["timeout_seconds"] = min(spec["timeout_seconds"], remaining)
            task = await asyncio.to_thread(self.store.prepare, task)
            adapter = self.adapters[spec["provider"]]
            key = (spec["provider"], spec["continuation"] != "none")
            if isinstance(adapter, CLIAdapter) and key not in self.preflighted:
                if key[1]:
                    await asyncio.to_thread(adapter.preflight, self.store.root, True)
                else:
                    await asyncio.to_thread(adapter.preflight, self.store.root)
                self.preflighted.add(key)
            elif isinstance(adapter, CLIAdapter):
                await asyncio.to_thread(adapter.verify_account)
            result = await adapter.run(spec, prompt_for(self.store, task),
                                      lambda: self.store.task(task["id"])["state"] == "cancelling",
                                      self.shutdown, self.store.limits.output_bytes)
            if result.recovery_required:
                self.uncertain = True
                self.shutdown.set()
                self.store.require_recovery(result.detail)
            await asyncio.to_thread(self.store.finish, task["id"], self.owner, task["attempt"], result.state, result.output, result.detail, result.session_id)
        except Exception as exc:
            # No automatic retry after either a preflight or an uncertain execution failure.
            await asyncio.to_thread(self.store.finish, task["id"], self.owner, task["attempt"], "failed", "", type(exc).__name__ + ": " + str(exc))

    async def run(self, once=False):
        with runner_lock(self.store):
            self.store.start_session()
            loop = asyncio.get_running_loop()
            signals = []
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.shutdown.set)
                    signals.append(sig)
                except (NotImplementedError, RuntimeError):
                    pass
            deadline = time.monotonic() + self.store.limits.run_seconds
            next_heartbeat = 0
            next_poll = 0
            try:
                while True:
                    if time.monotonic() >= next_heartbeat:
                        self.store.heartbeat()
                        next_heartbeat = time.monotonic() + 5
                    if self.store.stopping() or time.monotonic() >= deadline:
                        self.shutdown.set()
                    for task_id, future in list(self.active.items()):
                        if future.done():
                            future.result()
                            del self.active[task_id]
                    if not self.shutdown.is_set() and self.watch_policy and time.monotonic() >= next_poll:
                        from .factory import watch_once
                        await asyncio.to_thread(watch_once, self.store, self.watch_policy, self.auto_approve, self.approval_evidence)
                        next_poll = time.monotonic() + self.poll_seconds
                    if not self.shutdown.is_set():
                        while len(self.active) < self.store.limits.workers:
                            task = self.store.claim(self.owner, live=self.live)
                            if task is None:
                                break
                            self.active[task["id"]] = asyncio.create_task(self.execute(task))
                    if not self.active and (once or self.shutdown.is_set()):
                        break
                    await asyncio.sleep(0.05 if self.active else 0.5)
            finally:
                self.shutdown.set()
                await asyncio.gather(*self.active.values(), return_exceptions=False)
                for sig in signals:
                    loop.remove_signal_handler(sig)
                if not self.uncertain:
                    self.store.clean_session()  # never erase dirty state after a failed uncertainty write
