"""Folder factory, routing and work protection without any paid provider calls."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from test_superagent import Fixture, ROOT
from superagent.adapters import ChecksAdapter, CLIAdapter
from superagent.factory import load_policy, import_folder, approve_factory, factory_status, read_backlog, route
from superagent.runtime import Runner
from superagent.safety import SafetyError
from superagent.workspace import fingerprint


class FactoryFixture(Fixture):
    def setUp(self):
        super().setUp()
        self.folder = self.base / "backlog"
        self.folder.mkdir()
        self.policy_file = self.base / "policy.json"
        self.policy = {"id": "batch-1", "backlog_id": "board-1", "folder": str(self.folder), "project": "demo",
                       "selected_ids": ["item-1"], "workspaces": {"item-1": str(self.ws)}, "paths": ["src", "tests"],
                       "profiles": {"small": {"provider": "mock", "model": "mock-routine", "tier": "routine"},
                                    "strong": {"provider": "mock", "model": "mock-strong", "tier": "strong"}},
                       "routing": {"plan": "strong", "build": "small", "security": "strong"},
                       "risk_by_item": {"item-1": "routine"}, "checks": ["git-diff-check"], "budget_cents": 100}
        self.item = {"id": "item-1", "title": "Example", "description": "Build scoped functionality", "acceptance": "Works with tests",
                     "dependencies": [], "ready": True}
        self.write()

    def write(self):
        (self.folder / "item.json").write_text(json.dumps(self.item))
        self.policy_file.write_text(json.dumps(self.policy))

    def load(self):
        return load_policy(self.store, self.policy_file)

class FactoryTests(FactoryFixture):
    def test_import_is_readonly_deduplicated_and_never_approves(self):
        before = (self.folder / "item.json").read_bytes()
        status = import_folder(self.store, self.load())
        import_folder(self.store, self.load())
        self.assertEqual(len(self.store.tasks()), 4)
        self.assertEqual(self.store.status()["states"], {"draft": 4})
        self.assertIsNone(self.store.claim("owner"))
        self.assertEqual((self.folder / "item.json").read_bytes(), before)
        self.assertEqual(len(self.store.events()), 1)
        self.assertTrue(all(len(self.store.events(t["id"])) == 1 for t in self.store.tasks()))

    def test_mock_pipeline_runs_plan_build_checks_security_with_review_gate(self):
        import_folder(self.store, self.load())
        approve_factory(self.store, "batch-1", "Selected items and frozen routes approved for mock execution")
        asyncio.run(Runner(self.store).run(once=True))
        status = factory_status(self.store, "batch-1")
        self.assertTrue(status["items"][0]["ready_for_owner_review"])
        self.assertFalse(status["items"][0]["accepted"])
        self.assertEqual(self.store.status()["states"], {"completed": 4})
        routes = {s["stage"]: s["routing"] for s in status["items"][0]["stages"]}
        self.assertEqual(routes["plan"]["profile"], "strong")
        self.assertEqual(routes["build"]["profile"], "small")
        self.assertEqual(routes["checks"]["profile"], "fixed-tools")
        self.assertEqual(routes["security"]["profile"], "strong")
        self.assertEqual(self.store.status()["reserved_cents"], 300)
        security = status["items"][0]["stages"][-1]["task_id"]
        self.store.accept(security, "Independent owner review of mock evidence only")
        self.assertTrue(factory_status(self.store, "batch-1")["items"][0]["accepted"])

    def test_changed_item_never_inherits_approval_or_overwrites(self):
        import_folder(self.store, self.load())
        old = self.store.tasks()
        self.item["description"] = "Changed content claiming new access"
        self.write()
        with self.assertRaisesRegex(SafetyError, "revision conflict"):
            import_folder(self.store, self.load())
        self.assertEqual(self.store.tasks(), old)

    def test_export_cannot_select_model_privileges_or_downgrade_risk(self):
        for key, value in (("provider", "codex"), ("mode", "workspace-write"), ("risk", "routine"), ("approved", True)):
            data = dict(self.item, **{key: value})
            (self.folder / "item.json").write_text(json.dumps(data))
            with self.subTest(key=key), self.assertRaises(SafetyError):
                import_folder(self.store, self.load())
        self.assertEqual(self.store.tasks(), [])

    def test_unknown_or_high_risk_uses_strong_and_override_is_explicit(self):
        policy = self.load()
        policy["risk_by_item"] = {}
        profile, decision = route(policy, "item-1", "build")
        self.assertEqual(profile["tier"], "strong")
        self.assertIn("high/unknown", decision["reason"])
        policy["overrides"] = {"item-1": {"build": "small"}}
        with self.assertRaises(SafetyError):
            route(policy, "item-1", "build")
        policy["risk_by_item"]["item-1"] = "routine"
        profile, decision = route(policy, "item-1", "build")
        self.assertEqual(profile["tier"], "routine")
        self.assertEqual(decision["reason"], "explicit owner override")

    def test_model_aliases_no_automatic_credit_upgrade(self):
        for model in ("best", "fable", "default", "auto"):
            self.policy["profiles"]["strong"] = {"provider": "claude", "model": model, "tier": "strong"}
            self.write()
            with self.subTest(model=model), self.assertRaises(SafetyError):
                self.load()

    def test_cycles_missing_dependency_and_ineligible_selection_fail_before_drafts(self):
        for dependencies, ready in ((["item-1"], True), (["missing"], True), ([], False)):
            self.item.update(dependencies=dependencies, ready=ready)
            self.write()
            with self.subTest(dependencies=dependencies), self.assertRaises(SafetyError):
                import_folder(self.store, self.load())
        self.assertEqual(self.store.tasks(), [])

    def test_bad_partial_json_symlink_size_and_filecount_are_rejected(self):
        source = self.folder / "item.json"
        source.write_text('{"id":')
        with self.assertRaises(ValueError):
            read_backlog(self.folder)
        source.unlink()
        source.symlink_to(self.policy_file)
        with self.assertRaises(SafetyError):
            read_backlog(self.folder)
        source.unlink()
        source.write_text("x"*32769)
        with self.assertRaises(SafetyError):
            read_backlog(self.folder)
        source.unlink()
        for n in range(129):
            (self.folder / (str(n) + ".txt")).write_text("")
        with self.assertRaises(SafetyError):
            read_backlog(self.folder)

    def test_failed_dependencies_block_downstream_without_running(self):
        import_folder(self.store, self.load())
        approve_factory(self.store, "batch-1", "approved")
        plan = self.store.claim("owner")
        self.store.finish(plan["id"], "owner", plan["attempt"], "failed", "failure")
        self.assertIsNone(self.store.claim("owner"))
        stages = factory_status(self.store, "batch-1")["items"][0]["stages"]
        self.assertEqual([s["state"] for s in stages], ["failed", "blocked", "blocked", "blocked"])

    def test_live_auth_unknown_or_api_env_fails_closed_without_extracting_secrets(self):
        flags = "--safe-mode --restricted --permission-prompts --tools --max-budget-usd --max-turns --no-session-persistence --output-format --settings"
        adapter = CLIAdapter("claude", sys.executable)
        help_result = subprocess.CompletedProcess([], 0, flags.encode(), b"")
        auth_result = subprocess.CompletedProcess([], 0, b'{"authMethod":"api_key"}', b"")
        with patch.object(adapter, "resolve", return_value=sys.executable), patch("superagent.adapters.subprocess.run", side_effect=[help_result, auth_result]):
            with self.assertRaises(SafetyError):
                adapter.preflight(self.work)
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "fake-test-value"}), patch.object(adapter, "resolve", return_value=sys.executable), patch("superagent.adapters.subprocess.run", return_value=help_result) as run:
            with self.assertRaisesRegex(SafetyError, "environment"):
                adapter.preflight(self.work)
            self.assertEqual(run.call_count, 1)


class WorkProtectionTests(Fixture):
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.ws, check=True, capture_output=True, text=True).stdout.strip()

    def prepare(self):
        self.git("init", "-b", "superagent/test")
        self.git("config", "user.name", "Offline Test")
        self.git("config", "user.email", "offline@example.invalid")
        (self.ws / "file.txt").write_text("before\n")
        self.git("add", ".")
        self.git("commit", "-m", "baseline")

    def test_protected_branch_dirty_work_and_snapshot_conflicts(self):
        self.prepare()
        baseline = fingerprint(self.ws, clean=True)
        (self.ws / "file.txt").write_text("user changes\n")
        with self.assertRaises(SafetyError):
            fingerprint(self.ws, clean=True)
        self.assertNotEqual(fingerprint(self.ws), baseline)
        self.git("checkout", "-b", "main")
        with self.assertRaises(SafetyError):
            fingerprint(self.ws)
        self.assertEqual((self.ws / "file.txt").read_text(), "user changes\n")

    def test_external_change_after_approval_prevents_live_claim(self):
        self.prepare()
        self.queued(provider="codex", mode="workspace-write", paths=["file.txt"])
        (self.ws / "file.txt").write_text("user edit after approval\n")
        task = self.store.claim("owner", live=True)
        with self.assertRaisesRegex(SafetyError, "workspace changed"):
            self.store.prepare(task)
        # Admission is reserved, but no provider was launched.
        self.assertEqual(self.store.status()["reserved_cents"], 100)

    def test_acceptance_is_bound_to_result_workspace_snapshot(self):
        self.prepare()
        self.queued(provider="codex", mode="workspace-write", paths=["file.txt"])
        task = self.store.claim("owner", live=True)
        (self.ws / "file.txt").write_text("authorized worker output\n")
        self.store.finish("t1", "owner", task["attempt"], "completed", "offline captured result")
        (self.ws / "file.txt").write_text("later unreviewed user change\n")
        with self.assertRaisesRegex(SafetyError, "stale"):
            self.store.accept("t1", "old evidence")

    def test_fixed_checks_capture_real_exit_evidence_without_a_model(self):
        self.prepare()
        spec = self.store.validate_spec(self.spec(provider="checks", mode="workspace-write", paths=["file.txt"], checks=["git-diff-check"], budget_cents=0))
        async def run():
            return await ChecksAdapter().run(spec, "", lambda: False, asyncio.Event(), 65536)
        result = asyncio.run(run())
        self.assertEqual(result.state, "completed", result.detail)
        evidence = json.loads(result.output)["tool_evidence"]
        self.assertEqual(evidence[0]["check"], "git-diff-check")
        self.assertEqual(evidence[0]["exit_code"], 0)
        self.assertEqual(json.loads(result.output)["actual_model"], "none")
        (self.ws / "file.txt").write_text("bad trailing spaces  \n")
        result = asyncio.run(run())
        self.assertEqual(result.state, "failed")

    def test_out_of_scope_rename_delete_and_untracked_fail_writer_result(self):
        self.prepare()
        self.queued(provider='codex', mode='workspace-write', paths=['src'])
        task = self.store.claim('owner', live=True)
        self.git('mv', 'file.txt', 'src/moved.txt')
        self.store.finish('t1', 'owner', task['attempt'], 'completed', 'claimed success')
        self.assertEqual(self.store.task('t1')['state'], 'failed')
        self.assertIn('outside approved scope', self.store.task('t1')['detail'])
        self.assertTrue((self.ws / 'src/moved.txt').exists())  # no destructive rollback
        from superagent.workspace import enforce_changed_paths
        self.git('reset', '--hard', 'HEAD')  # disposable test fixture only
        (self.ws / 'outside.txt').write_text('untracked')
        with self.assertRaises(SafetyError):
            enforce_changed_paths(self.ws, ['src'])
        (self.ws / 'outside.txt').unlink()
        (self.ws / 'file.txt').unlink()
        with self.assertRaises(SafetyError):
            enforce_changed_paths(self.ws, ['src'])

    def test_source_change_during_protected_review_prevents_acceptance(self):
        self.prepare()
        self.queued(provider='codex', protect_workspace=True, paths=['file.txt'])
        task = self.store.claim('owner', live=True)
        task = self.store.prepare(task)
        (self.ws / 'file.txt').write_text('changed while reviewer was reading')
        self.store.finish('t1', 'owner', task['attempt'], 'completed', 'old review')
        self.assertEqual(self.store.task('t1')['state'], 'failed')
        with self.assertRaises(SafetyError):
            self.store.accept('t1', 'must rereview')

    def test_git_filters_never_execute_in_runtime_legacy_or_fixed_check_paths(self):
        import runpy
        import shlex
        self.prepare()
        (self.ws / '.gitattributes').write_text('*.txt filter=probe\n')
        self.git('add', '.gitattributes')
        self.git('commit', '-m', 'attributes before filter configuration')
        marker = self.base / 'FILTER_MUST_NOT_EXECUTE'
        command = 'touch ' + shlex.quote(str(marker)) + '; cat'
        from superagent.workspace import review_context, git_command
        prefix, env = git_command(self.ws)
        self.assertEqual(env['GIT_NO_LAZY_FETCH'], '1')
        self.assertEqual(env['GIT_ALLOW_PROTOCOL'], '')
        self.assertIn('protocol.allow=never', prefix)
        handoff = runpy.run_path(str(ROOT / '.claude/skills/delegate/scripts/handoff.py'))
        old = Path.cwd()
        try:
            os.chdir(self.ws)
            for name in ('clean', 'process', 'smudge'):
                self.git('config', 'filter.probe.' + name, command)
                with self.subTest(filter=name):
                    with self.assertRaises(SafetyError):
                        fingerprint(self.ws)
                    with self.assertRaises(SafetyError):
                        review_context(self.ws, 'unused')
                    with self.assertRaises(ValueError):
                        handoff['git']('status', '--short')
                    review = subprocess.run(['bash', str(ROOT / '.claude/skills/delegate/scripts/review-git.sh'), 'status'], capture_output=True)
                    self.assertNotEqual(review.returncode, 0)
                    spec = self.store.validate_spec(self.spec(provider='checks', mode='workspace-write', paths=['file.txt'], checks=['git-diff-check'], budget_cents=0))
                    result = asyncio.run(ChecksAdapter().run(spec, '', lambda: False, asyncio.Event(), 65536))
                    self.assertEqual(result.state, 'failed')
                    self.assertFalse(marker.exists(), 'a Git inspection executed repository filter code')
                self.git('config', '--unset', 'filter.probe.' + name)
        finally:
            os.chdir(old)
