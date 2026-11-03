"""Single local scheduler; durable state is independent of in-memory execution."""
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
import signal
import time
import uuid

from .adapters import CLIAdapter, MockAdapter, prompt_for
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
    def __init__(self, store, live=False, isolated_host=False, external_budget_guard=False, adapters=None):
        if live and not (isolated_host and external_budget_guard):
            raise SafetyError("live execution requires isolated-host and external-budget-guard acknowledgements")
        self.store = store
        self.live = live
        self.adapters = adapters or {"mock": MockAdapter(), "claude": CLIAdapter("claude"), "codex": CLIAdapter("codex")}
        self.owner = uuid.uuid4().hex
        self.shutdown = asyncio.Event()
        self.active = {}
        self.preflighted = set()

    async def execute(self, task):
        spec = json.loads(task["spec"])
        try:
            adapter = self.adapters[spec["provider"]]
            if isinstance(adapter, CLIAdapter) and spec["provider"] not in self.preflighted:
                await asyncio.to_thread(adapter.preflight, self.store.root)
                self.preflighted.add(spec["provider"])
            result = await adapter.run(spec, prompt_for(self.store, task),
                                      lambda: self.store.task(task["id"])["state"] == "cancelling",
                                      self.shutdown, self.store.limits.output_bytes)
            self.store.finish(task["id"], self.owner, task["attempt"], result.state, result.output, result.detail)
        except Exception as exc:
            # No automatic retry after either a preflight or an uncertain execution failure.
            self.store.finish(task["id"], self.owner, task["attempt"], "failed", "", type(exc).__name__ + ": " + str(exc))

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
            try:
                while True:
                    if self.store.heartbeat() or time.monotonic() >= deadline:
                        self.shutdown.set()
                    for task_id, future in list(self.active.items()):
                        if future.done():
                            future.result()
                            del self.active[task_id]
                    if not self.shutdown.is_set():
                        while len(self.active) < self.store.limits.workers:
                            task = self.store.claim(self.owner, live=self.live)
                            if task is None:
                                break
                            self.active[task["id"]] = asyncio.create_task(self.execute(task))
                    if not self.active and (once or self.shutdown.is_set()):
                        break
                    await asyncio.sleep(0.05)
            finally:
                self.shutdown.set()
                await asyncio.gather(*self.active.values(), return_exceptions=False)
                for sig in signals:
                    loop.remove_signal_handler(sig)
                self.store.clean_session()
