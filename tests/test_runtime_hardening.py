"""Regression tests for integration, isolation contracts, recovery and watcher limits."""
import asyncio
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from unittest.mock import AsyncMock, patch

from test_superagent import Fixture, ROOT
from test_factory import FactoryFixture
from superagent.adapters import CLIAdapter, ChecksAdapter, Outcome, prompt_for
from superagent.checks_worker import UNITTEST, command_for
from superagent.factory import manifest, watch_once, import_folder, approve_factory, factory_status
from superagent.migration import migrate
from superagent.runtime import Runner
from superagent.safety import SafetyError, encoded
from superagent.state import Limits, Store


class HardeningTests(Fixture):
    def test_unicode_owner_constraint_is_never_truncated(self):
        self.queued(continuation="owner")
        text = "😀" * 4000 + " DO_NOT_EDIT_ANY_FILES_FINAL_CONSTRAINT"
        self.store.instruct("t1", "unicode", text)
        prompt = prompt_for(self.store, self.store.claim("owner"))
        self.assertIn("DO_NOT_EDIT_ANY_FILES_FINAL_CONSTRAINT", prompt)

    def test_invalid_first_report_holds_but_keeps_verified_session(self):
        self.queued(continuation="owner")
        task = self.store.claim("owner")
        self.store.finish("t1", "owner", task["attempt"], "completed", encoded({"result": "not valid report"}), session_id="owned_session")
        self.assertEqual(self.store.task("t1")["state"], "held")
        self.assertEqual(self.store.task("t1")["session_id"], "owned_session")
        self.store.instruct("t1", "clarify", "Return the requested bounded report")
        self.assertEqual(self.store.claim("owner")["session_id"], "owned_session")

    def test_expiry_during_preflight_never_launches_cli(self):
        self.queued(provider="codex", lifetime_seconds=1)
        class Slow(CLIAdapter):
            def preflight(inner, root):
                time.sleep(1.1)
        async def run():
            await Runner(self.store, True, True, True, adapters={"codex": Slow("codex", "/not/a/client")}).run(True)
        with patch("superagent.adapters.asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            asyncio.run(run())
            self.assertEqual(spawn.await_count, 0)
        self.assertEqual(self.store.task("t1")["state"], "cancelled")

    def test_docker_contract_is_pinned_no_network_and_has_owned_cleanup(self):
        image = "python@sha256:" + "a"*64
        name = "superagent-" + "b"*32
        command = command_for("python-unittest", image, self.ws, "/trusted/docker", name)
        for value in ("--pull=never", "--network=none", "--read-only", "--cap-drop=ALL", "--entrypoint", "--user=" + str(os.getuid()) + ":" + str(os.getgid()), name, image):
            self.assertIn(value, command)
        self.assertEqual(command[command.index("--entrypoint")+1], "python3")
        source = self.ws / 'private-source.py'
        source.write_text('# ordinary private source')
        source.chmod(0o600)
        self.assertEqual(source.stat().st_uid, os.getuid())
        with patch('superagent.checks_worker.os.getuid', return_value=0):
            with self.assertRaises(ValueError):
                command_for('python-unittest', image, self.ws, '/trusted/docker', name)
        self.assertEqual(source.stat().st_mode & 0o777, 0o600)
        self.assertFalse(any("docker.sock" in part for part in command[command.index("--mount")+1:]))
        with self.assertRaises(ValueError):
            command_for("python-unittest", "python:latest", self.ws, "/trusted/docker", name)
        adapter = ChecksAdapter()
        outputs = [subprocess.CompletedProcess([], 0, ("abc123 " + name + "\n").encode(), b""),
                   subprocess.CompletedProcess([], 0, b"abc123", b""), subprocess.CompletedProcess([], 0, b"", b"")]
        with patch("superagent.adapters.subprocess.run", side_effect=outputs) as call:
            self.assertTrue(adapter.cleanup_container("/trusted/docker", name))
            self.assertIn(["/trusted/docker", "--host", "unix:///var/run/docker.sock", "rm", "--force", "abc123"], [c.args[0] for c in call.call_args_list])

    def test_container_launch_exception_cannot_lose_recovery_barrier(self):
        spec = self.store.validate_spec(self.spec(provider="checks", mode="workspace-write", checks=["python-unittest"],
                                                check_image="python@sha256:" + "a"*64, budget_cents=0))
        spec.update(_attempt="b"*32, _workspace_root=str(self.work))
        adapter = ChecksAdapter()
        async def run():
            return await adapter.run(spec, "", lambda: False, asyncio.Event(), 65536)
        with patch("superagent.adapters.shutil.which", return_value=sys.executable), \
             patch.object(CLIAdapter, "run", new_callable=AsyncMock, side_effect=OSError("launch uncertain")), \
             patch.object(adapter, "cleanup_container", return_value=False):
            result = asyncio.run(run())
        self.assertTrue(result.recovery_required)
        self.assertEqual(result.state, "interrupted")

    def test_unittest_harness_nonpackage_tests_and_zero_discovery(self):
        folder = self.ws / "tests"
        folder.mkdir()
        empty = subprocess.run([sys.executable, "-I", "-B", "-c", UNITTEST], cwd=self.ws, capture_output=True, text=True)
        self.assertEqual(empty.returncode, 2)
        self.assertIn("No tests discovered", empty.stdout)
        (folder / "test_example.py").write_text("import unittest\nclass Example(unittest.TestCase):\n def test_ok(self): self.assertEqual(1,1)\n")
        result = subprocess.run([sys.executable, "-I", "-B", "-c", UNITTEST], cwd=self.ws, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('"run": 1', result.stdout)

    def test_installed_both_clients_are_self_contained_shadow_safe_and_idempotent(self):
        source = self.base / "source checkout with spaces"
        shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        destinations = []
        for client in ("claude", "codex"):
            dest = self.base / ("installed " + client)
            result = subprocess.run(["bash", str(source / "install.sh"), "--client", client, "--dest", str(dest)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            destinations.append((client, dest))
        moved = self.base / "source moved"
        source.rename(moved)
        (self.ws / "superagent.py").write_text("raise RuntimeError('shadowed module')\n")
        (self.ws / "sitecustomize.py").write_text("raise RuntimeError('shadowed startup')\n")
        for client, dest in destinations:
            skill = dest / "skills" / ("delegate" if client == "claude" else "superagent")
            helper = skill / "scripts/superagent.sh"
            result = subprocess.run(["bash", str(helper), "--state", str(self.state), "status"], cwd=self.ws,
                                    env=dict(os.environ, PYTHONPATH=str(self.ws)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(skill.rglob("__pycache__")), [])
            reinstall = subprocess.run(["bash", str(moved / "install.sh"), "--client", client, "--dest", str(dest)], capture_output=True, text=True)
            self.assertEqual(reinstall.returncode, 0, reinstall.stderr)
            self.assertIn("Already installed", reinstall.stdout)

    def test_legacy_migration_has_backup_preserves_budget_and_never_replays(self):
        directory = self.base / "legacy"
        directory.mkdir(mode=0o700)
        database = directory / "state.sqlite3"
        fd = os.open(str(database), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        os.close(fd)
        with sqlite3.connect(database) as db:
            db.executescript((ROOT / "tests/fixtures/state-v1.sql").read_text())
            db.executemany("INSERT INTO settings VALUES (?,?)", {"version": "1", "workspace_root": encoded(str(self.work)), "repository": encoded("example/project"),
                "limits": encoded(asdict(Limits())), "dirty": "1", "recovery_required": "0", "stop": "0", "heartbeat": "0"}.items())
            db.execute("INSERT INTO tasks(id,spec,state,created,updated,owner,attempt) VALUES ('old',?,'running',?,?,'old-owner','old-attempt')", (encoded(self.spec("old")), time.time(), time.time()))
            db.execute("INSERT INTO attempts VALUES ('old-attempt','old','old-owner',?,NULL,'running',100,'old-context')", (time.time(),))
        with self.assertRaises(SafetyError):
            Store(directory)
        with patch.object(Store, 'validate_spec', side_effect=SafetyError('invalid legacy spec')):
            with self.assertRaises(SafetyError):
                migrate(directory, 'Rollback test after worker inspection')
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT value FROM settings WHERE key='version'").fetchone()[0], '1')
            self.assertNotIn('session_id', [r[1] for r in db.execute('PRAGMA table_info(tasks)')])
        for backup in directory.glob('pre-v2-*.sqlite3'):
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        report = migrate(directory, "Old workers stopped; prior effects inspected")
        self.assertTrue(Path(report["backup"]).is_file())
        current = Store(directory)
        self.assertEqual(current.task("old")["state"], "interrupted")
        self.assertEqual(current.status()["reserved_cents"], 100)
        self.assertIsNone(current.claim("new-owner"))
        self.assertFalse(migrate(directory, "Already migrated")["changed"])


class WatchAndRepairTests(FactoryFixture):
    # Inherits folder fixtures and exercises the same full basic factory contracts.
    def test_watcher_requires_manifest_and_never_admits_unselected_files(self):
        policy = self.load()
        report = watch_once(self.store, policy, True, "bounded approval")
        self.assertEqual(report["status"], "held")
        self.assertEqual(self.store.tasks(), [])
        hashes = {item["id"]: item["content_hash"] for item in manifest(self.folder)["items"]}
        self.policy["approved_hashes"] = hashes
        self.write()
        policy = self.load()
        extra = dict(self.item, id="unapproved", title="Do not admit")
        (self.folder / "extra.json").write_text(json.dumps(extra))
        report = watch_once(self.store, policy, True, "only exact selected hashes approved")
        self.assertEqual(report["status"], "observed")
        self.assertEqual(report["pending_unapproved_ids"], ["unapproved"])
        self.assertEqual(len(self.store.tasks()), 4)
        asyncio.run(Runner(self.store).run(True))
        spent = self.store.status()["reserved_cents"]
        watch_once(self.store, policy, True, "same approval")
        asyncio.run(Runner(self.store).run(True))
        self.assertEqual(self.store.status()["reserved_cents"], spent)
        self.item["description"] = "changed after approval"
        self.write()
        self.assertEqual(watch_once(self.store, policy, True, "same approval")["status"], "held")
        self.assertEqual(len(self.store.tasks()), 4)

    def test_concurrent_repair_creation_cannot_exceed_two_drafts(self):
        from concurrent.futures import ThreadPoolExecutor
        self.store.create_task(self.spec('original', mode='workspace-write'))
        def create(number):
            try:
                self.store.create_task(self.spec('repair-' + str(number), repair_of='original'))
                return True
            except SafetyError:
                return False
        with ThreadPoolExecutor(max_workers=3) as pool:
            self.assertEqual(sum(pool.map(create, range(3))), 2)

    def test_repair_bridge_creates_draft_with_original_scope_and_two_draft_cap(self):
        import_folder(self.store, self.load())
        approve_factory(self.store, "batch-1", "mock scope approved")
        asyncio.run(Runner(self.store).run(True))
        stages = factory_status(self.store, "batch-1")["items"][0]["stages"]
        build, check = stages[1]["task_id"], stages[2]["task_id"]
        first = self.store.repair_draft(build, check, "repair-1", "Fix the same approved functionality")
        self.assertEqual(self.store.task(first)["state"], "draft")
        spec = json.loads(self.store.task(first)["spec"])
        original = json.loads(self.store.task(build)["spec"])
        self.assertEqual(spec["paths"], original["paths"])
        self.assertEqual(spec["model"], original["model"])
        self.assertEqual(spec["previous_task"], check)
        self.store.repair_draft(build, check, "repair-2", "Second scoped repair proposal")
        with self.assertRaises(SafetyError):
            self.store.repair_draft(build, check, "repair-3", "No unbounded repair loop")

class ResponsivenessTests(Fixture):
    def test_uncertain_execution_sets_global_recovery_and_stops_runner(self):
        self.queued()
        class Uncertain:
            async def run(inner, *args):
                return Outcome('interrupted', '', 'container cleanup uncertain', recovery_required=True)
        runner = Runner(self.store, adapters={'mock': Uncertain()})
        real_finish = self.store.finish
        calls = []
        def interrupted_write(*args):
            calls.append(1)
            if len(calls) == 1:
                raise SafetyError('result artifact full')
            return real_finish(*args)
        with patch.object(self.store, 'finish', side_effect=interrupted_write):
            asyncio.run(runner.run(True))
        self.assertTrue(runner.shutdown.is_set())
        with self.store.connection(write=False) as db:
            self.assertEqual(self.store._get(db, 'recovery_required'), '1')
        self.assertIsNone(self.store.claim('late-owner'))

    def test_failed_recovery_barrier_write_never_marks_uncertain_session_clean(self):
        self.queued()
        class Uncertain:
            async def run(inner, *args):
                return Outcome('interrupted', '', 'container cleanup uncertain', recovery_required=True)
        runner = Runner(self.store, adapters={'mock': Uncertain()})
        with patch.object(self.store, 'require_recovery', side_effect=SafetyError('temporary DB failure')):
            asyncio.run(runner.run(True))
        self.assertTrue(runner.uncertain)
        self.assertEqual(self.store.status()['settings']['dirty'], '1')
        with self.assertRaises(SafetyError):
            Store(self.state).start_session()
        self.assertEqual(self.store.status()['settings']['recovery_required'], '1')

    def test_slow_finish_git_scan_does_not_hold_database_writer_lock(self):
        with patch('superagent.state.fingerprint', return_value='snapshot'):
            self.queued(provider='codex', protect_workspace=True)
        task = self.store.claim('owner', live=True)
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def slow(workspace):
            entered.set()
            release.wait(3)
            return 'snapshot'
        def finish():
            try:
                self.store.finish('t1', 'owner', task['attempt'], 'completed', 'result')
            except Exception as exc:
                errors.append(exc)
        def cancel():
            self.store.cancel('t1')
            cancelled.set()
        with patch('superagent.state.fingerprint', side_effect=slow):
            worker = threading.Thread(target=finish)
            worker.start()
            self.assertTrue(entered.wait(2))
            control = threading.Thread(target=cancel)
            control.start()
            responsive = cancelled.wait(1)
            release.set()
            worker.join(3)
            control.join(3)
        self.assertTrue(responsive, 'fingerprint held SQLite writer lock')
        self.assertFalse(errors)
        self.assertEqual(self.store.task('t1')['state'], 'cancelled')

    def test_cached_capabilities_still_recheck_account_each_turn(self):
        self.queued(provider='codex')
        self.queued('t2', provider='codex')
        adapter = CLIAdapter('codex', sys.executable)
        runner = Runner(self.store, True, True, True, adapters={'codex': adapter})
        async def run():
            for _ in range(2):
                task = self.store.claim(runner.owner, live=True)
                await runner.execute(task)
        with patch.object(adapter, 'preflight') as first, patch.object(adapter, 'verify_account') as later, \
             patch.object(adapter, 'run', new_callable=AsyncMock, return_value=Outcome('completed', 'fake')):
            asyncio.run(run())
            self.assertEqual(first.call_count, 1)  # real preflight also checks auth
            self.assertEqual(later.call_count, 1)

    def test_live_automatic_credit_aliases_fail_before_launch(self):
        for model in ('default', 'best', 'fable', 'auto'):
            spec = self.store.validate_spec(self.spec(provider='codex', model=model))
            with self.subTest(model=model), self.assertRaises(SafetyError):
                CLIAdapter('codex', sys.executable).command(spec)
