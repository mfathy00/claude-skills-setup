"""Offline integration tests: every model executable is a fake, every HOME is temporary."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

SOURCE = Path(__file__).resolve().parents[1]
SCRIPTS = SOURCE / '.claude/skills/delegate/scripts'
BASH = shutil.which('bash')
GIT = shutil.which('git')
PYTHON = shutil.which('python3')


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delegate tests ')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / 'home'
        self.home.mkdir()
        self.repo = self.base / 'repo with spaces'
        self.repo.mkdir()
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        for name, target in (('git', GIT), ('python3', PYTHON), ('bash', BASH), ('dirname', shutil.which('dirname'))):
            (self.bin / name).symlink_to(target)
        self.env = dict(os.environ, HOME=str(self.home), GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL=os.devnull, PATH=str(self.bin) + os.pathsep + '/usr/bin:/bin',
                        MOCK_LOG=str(self.base / 'mock.json'), MOCK_MODE='ok')
        self.run_cmd([GIT, 'init', '-q'])
        (self.repo / 'app.txt').write_text('original\n')
        self.run_cmd([GIT, 'add', '.'])
        self.run_cmd([GIT, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'fixture'])
        self.fake_codex()

    def run_cmd(self, command, ok=True, cwd=None, env=None):
        result = subprocess.run(command, cwd=cwd or self.repo, env=env or self.env,
                                capture_output=True, text=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def fake_codex(self):
        path = self.bin / 'codex'
        path.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
pathlib.Path(os.environ['MOCK_LOG']).write_text(json.dumps({'args': args, 'prompt': prompt, 'cwd': os.getcwd()}))
mode = os.environ.get('MOCK_MODE', 'ok')
if mode == 'fail': sys.exit(23)
if mode == 'slow': time.sleep(0.4)
if mode != 'empty':
    pathlib.Path(args[args.index('--output-last-message')+1]).write_text('Completed mock track; no model called.\\n')
''')
        path.chmod(0o755)

    def write(self, run='run1', track='CX1', extra=(), ok=True, cwd=None):
        return self.run_cmd([BASH, str(SCRIPTS / 'write-handoff.sh'), '--run-id', run,
                             '--track', track, '--goal', 'Fix the scoped fixture', *extra], ok=ok, cwd=cwd)

    def directory(self, run='run1', track='CX1'):
        return self.repo / '.claude/delegate-runs' / run / track

    def complete(self, run='run1', track='CX1'):
        file = self.directory(run, track) / 'handoff.md'
        text = file.read_text().replace('TODO: fill from this session; use None where appropriate', 'None; inspect app.txt and report verification.')
        file.write_text(text)

    def launch(self, run='run1', track='CX1', extra=(), ok=True, approve=True):
        return self.run_cmd([BASH, str(SCRIPTS / 'handoff-to-codex.sh'), '--run-id', run,
                             '--track', track, *(['--approve'] if approve else []), *extra], ok=ok)

    def assert_no_launch(self):
        self.assertFalse((self.base / 'mock.json').exists())


class HandoffTests(Sandbox):
    def test_draft_and_placeholder_rejection(self):
        self.write()
        self.assert_no_launch()
        result = self.launch(ok=False)
        self.assertIn('placeholder', result.stderr)
        self.assert_no_launch()

    def test_legitimate_todo_prose_and_filename_are_not_placeholders(self):
        self.write(extra=['--goal', 'Build a todo app with offline storage'])
        self.complete()
        handoff = self.directory() / 'handoff.md'
        handoff.write_text(handoff.read_text().replace('inspect app.txt', 'inspect TODO.md'))
        self.launch()

    def test_approval_and_plan_only(self):
        self.write()
        self.complete()
        self.launch(approve=False, ok=False)
        self.launch(extra=['--plan-only'])
        self.assert_no_launch()
        self.assertFalse((self.directory() / 'started.json').exists())

    def test_missing_draft_no_automatic_generation(self):
        self.launch(ok=False)
        self.assertFalse(self.directory().exists())
        self.assert_no_launch()

    def test_success_from_subdirectory_and_exact_paths(self):
        subdir = self.repo / 'nested directory'
        subdir.mkdir()
        self.write(cwd=subdir, extra=['--model', 'example-model'])
        self.complete()
        out = self.directory() / 'result.md'
        self.launch(extra=['--handoff', str(self.directory() / 'handoff.md'), '--output', str(out), '--sandbox', 'workspace-write'])
        log = json.loads((self.base / 'mock.json').read_text())
        self.assertEqual(log['cwd'], str(self.repo))
        self.assertEqual(log['args'][:3], ['exec', '--sandbox', 'workspace-write'])
        self.assertIn('approval_policy="never"', log['args'])
        self.assertIn('sandbox_workspace_write.network_access=false', log['args'])
        self.assertIn('example-model', log['args'])
        self.assertEqual(log['args'][-1], '-')
        self.assertIn('Fix the scoped fixture', log['prompt'])
        outcome = json.loads((self.directory() / 'outcome.json').read_text())
        self.assertEqual(outcome['exit_code'], 0)
        self.assertEqual(outcome['actual_model'], 'unknown')
        self.launch(ok=False)  # no duplicate work or overwrite

    def test_writer_never_overwrites(self):
        self.write()
        before = (self.directory() / 'handoff.md').read_bytes()
        self.write(ok=False)
        self.assertEqual(before, (self.directory() / 'handoff.md').read_bytes())

    def test_stale_and_future_timestamps(self):
        for run, value in [('old', time.time() - 86401), ('future', time.time() + 600)]:
            with self.subTest(run=run):
                self.write(run)
                self.complete(run)
                manifest = self.directory(run) / 'manifest.json'
                data = json.loads(manifest.read_text())
                data['created_at'] = value
                manifest.write_text(json.dumps(data))
                self.assertIn('timestamp', self.launch(run, ok=False).stderr)
        self.assert_no_launch()

    def test_changed_tracked_and_untracked_content(self):
        for run, name in [('tracked', 'app.txt'), ('untracked', 'new.txt')]:
            with self.subTest(run=run):
                path = self.repo / name
                path.write_text('before')
                self.write(run)
                self.complete(run)
                path.write_text('after!')
                self.assertIn('Repository changed', self.launch(run, ok=False).stderr)
        self.assert_no_launch()

    def test_changed_index_with_unchanged_worktree_is_stale(self):
        path = self.repo / 'app.txt'
        path.write_text('staged A\n')
        self.run_cmd([GIT, 'add', 'app.txt'])
        path.write_text('original\n')
        self.write()
        self.complete()
        path.write_text('staged B\n')
        self.run_cmd([GIT, 'add', 'app.txt'])
        path.write_text('original\n')
        self.assertIn('Repository changed', self.launch(ok=False).stderr)
        self.assert_no_launch()

    def test_snapshot_does_not_execute_configured_fsmonitor(self):
        marker = self.base / 'fsmonitor-ran'
        hook = self.repo / '.git/hooks/audit-fsmonitor'
        hook.write_text('#!' + BASH + '\ntouch "' + str(marker) + '"\n')
        hook.chmod(0o755)
        self.run_cmd([GIT, 'config', 'core.fsmonitor', '.git/hooks/audit-fsmonitor'])
        self.run_cmd([GIT, 'status', '--porcelain'])  # prove the safe fixture hook works
        self.assertTrue(marker.exists())
        marker.unlink()
        self.write()
        self.complete()
        self.launch()
        self.assertFalse(marker.exists())

    def test_changed_head(self):
        self.write()
        self.complete()
        self.run_cmd([GIT, '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'new head'])
        self.launch(ok=False)
        self.assert_no_launch()

    def test_path_traversal_external_output_and_symlinks(self):
        self.write(run='../escape', ok=False)
        self.write(extra=['--out', str(self.base / 'outside.md')], ok=False)
        self.write()
        self.complete()
        self.launch(extra=['--output', str(self.base / 'outside.md')], ok=False)
        (self.directory() / 'result.md').symlink_to(self.base / 'outside.md')
        self.launch(ok=False)
        self.assertFalse((self.base / 'outside.md').exists())
        self.assert_no_launch()

    def test_symlinked_state_parent(self):
        (self.repo / '.claude').mkdir()
        (self.repo / '.claude/delegate-runs').symlink_to(self.base, target_is_directory=True)
        self.write(ok=False)
        self.assertFalse((self.base / 'run1').exists())

    def test_mismatched_identity_and_empty_sections(self):
        self.write()
        self.complete()
        manifest = self.directory() / 'manifest.json'
        data = json.loads(manifest.read_text())
        data['track'] = 'wrong'
        manifest.write_text(json.dumps(data))
        self.launch(ok=False)
        data['track'] = 'CX1'
        manifest.write_text(json.dumps(data))
        handoff = self.directory() / 'handoff.md'
        handoff.write_text(handoff.read_text().replace('## Acceptance criteria', '## Wrong section'))
        self.launch(ok=False)
        self.assert_no_launch()

    def test_missing_codex_preserves_draft_without_start_marker(self):
        self.write()
        self.complete()
        (self.bin / 'codex').unlink()
        # Controlled PATH excludes any real installed model client.
        self.env['PATH'] = str(self.bin)
        self.assertIn('codex not found', self.launch(ok=False).stderr)
        self.assertTrue((self.directory() / 'handoff.md').exists())
        self.assertFalse((self.directory() / 'started.json').exists())
        self.assert_no_launch()

    def test_codex_failure_and_empty_result(self):
        for run, mode, code in [('failure', 'fail', 23), ('noresult', 'empty', 1)]:
            with self.subTest(mode=mode):
                self.write(run)
                self.complete(run)
                self.env['MOCK_MODE'] = mode
                result = self.launch(run, ok=False)
                self.assertEqual(result.returncode, code)
                outcome = json.loads((self.directory(run) / 'outcome.json').read_text())
                self.assertEqual(outcome['exit_code'], code)
                self.launch(run, ok=False)  # retries are not automatic

    def test_parallel_tracks_have_isolated_results(self):
        self.env['MOCK_MODE'] = 'slow'
        processes = []
        for track in ('CX1', 'CX2'):
            self.write(track=track)
            self.complete(track=track)
        for track in ('CX1', 'CX2'):
            processes.append(subprocess.Popen([BASH, str(SCRIPTS / 'handoff-to-codex.sh'), '--run-id', 'run1', '--track', track, '--approve'], cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for process in processes:
            stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0, stdout + stderr)
        for track in ('CX1', 'CX2'):
            self.assertTrue((self.directory(track=track) / 'result.md').is_file())

    def test_parallel_duplicate_launch_is_rejected(self):
        self.write()
        self.complete()
        self.env['MOCK_MODE'] = 'slow'
        command = [BASH, str(SCRIPTS / 'handoff-to-codex.sh'), '--run-id', 'run1', '--track', 'CX1', '--approve']
        processes = [subprocess.Popen(command, cwd=self.repo, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for process in processes:
            process.communicate(timeout=10)
        self.assertEqual(sorted(p.returncode for p in processes), [0, 1])

    def test_bad_arguments_and_non_git_directory(self):
        self.run_cmd([BASH, str(SCRIPTS / 'write-handoff.sh'), '--goal'], ok=False)
        self.run_cmd([BASH, str(SCRIPTS / 'handoff-to-codex.sh')], ok=False)
        self.run_cmd([BASH, str(SCRIPTS / 'write-handoff.sh')], cwd=self.home, ok=False)
        self.assert_no_launch()


class InstallerTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.source = self.base / 'source copy'
        shutil.copytree(SOURCE, self.source, ignore=shutil.ignore_patterns('.git', '__pycache__'))
        self.destination = self.home / '.claude'

    def install(self, *args, ok=True):
        return self.run_cmd([BASH, str(self.source / 'install.sh'), *args], ok=ok)

    def tree(self, path):
        return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}

    def test_install_idempotence_and_invocation(self):
        self.install()
        self.assertTrue(os.access(self.destination / 'skills/delegate/scripts/write-handoff.sh', os.X_OK))
        self.assertIn('Already installed', self.install().stdout)
        self.assertTrue(os.access(SOURCE / 'install.sh', os.X_OK))

    def test_conflict_requires_replace_and_retains_backup(self):
        self.install()
        skill = self.destination / 'skills/delegate'
        (skill / 'custom.md').write_text('private customization')
        unrelated = self.destination / 'agents/other.md'
        unrelated.write_text('leave me alone')
        self.install(ok=False)
        self.assertTrue((skill / 'custom.md').exists())
        result = self.install('--replace')
        backup = Path(result.stdout.split('Backup / recovery directory: ')[1].splitlines()[0])
        self.assertEqual((backup / 'before/skills/delegate/custom.md').read_text(), 'private customization')
        self.assertEqual(unrelated.read_text(), 'leave me alone')

    def test_source_preflight_before_destination_mutation(self):
        (self.source / '.claude/agents/delegate-tester.md').unlink()
        self.install(ok=False)
        self.assertFalse(self.destination.exists())

    def test_symlink_and_bad_arguments_rejected(self):
        elsewhere = self.base / 'elsewhere'
        elsewhere.mkdir()
        self.destination.symlink_to(elsewhere, target_is_directory=True)
        self.install(ok=False)
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.install('--dest', ok=False)
        self.install('--unknown', ok=False)

    def test_failed_install_rolls_back_all_changed_targets(self):
        self.install()
        (self.destination / 'skills/delegate/custom.md').write_text('keep me')
        (self.destination / 'agents/delegate-explorer.md').write_text('custom explorer')
        before_skill = self.tree(self.destination / 'skills')
        before_agents = self.tree(self.destination / 'agents')
        fake = self.bin / 'mv'
        fake.write_text('#!' + BASH + '\ncase "$1" in */staged/agents/delegate-explorer.md) exit 99;; esac\nexec ' + shutil.which('mv') + ' "$@"\n')
        fake.chmod(0o755)
        self.install('--replace', ok=False)
        self.assertEqual(before_skill, self.tree(self.destination / 'skills'))
        self.assertEqual(before_agents, self.tree(self.destination / 'agents'))
        self.assertFalse((self.destination / '.delegate-install.lock').exists())

    def test_competing_installer_rechecks_conflicts_after_lock(self):
        alternate = self.base / 'alternate source'
        shutil.copytree(self.source, alternate)
        skill = alternate / '.claude/skills/delegate/SKILL.md'
        skill.write_text(skill.read_text() + '\nDifferent installer source.\n')
        ready = self.base / 'lock-ready'
        release = self.base / 'lock-release'
        wrapper = self.bin / 'mkdir'
        wrapper.write_text('#!/usr/bin/env python3\n'
            'import os, pathlib, sys, time\n'
            'if os.environ.get("PAUSE_INSTALL") and sys.argv[-1].endswith(".delegate-install.lock"):\n'
            '    pathlib.Path(os.environ["LOCK_READY"]).touch()\n'
            '    deadline = time.monotonic() + 10\n'
            '    while not pathlib.Path(os.environ["LOCK_RELEASE"]).exists():\n'
            '        if time.monotonic() > deadline: sys.exit(98)\n'
            '        time.sleep(0.02)\n'
            'os.execv(' + repr(shutil.which('mkdir')) + ', ["mkdir", *sys.argv[1:]])\n')
        wrapper.chmod(0o755)
        env = dict(self.env, PAUSE_INSTALL='1', LOCK_READY=str(ready), LOCK_RELEASE=str(release))
        process = subprocess.Popen([BASH, str(alternate / 'install.sh')], cwd=self.repo,
                                   env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'second installer did not reach lock')
            self.install()
            release.touch()
            stdout, stderr = process.communicate(timeout=10)
            self.assertNotEqual(process.returncode, 0, stdout + stderr)
            self.assertIn('--replace', stderr)
            self.assertEqual((self.destination / 'skills/delegate/SKILL.md').read_text(),
                             (self.source / '.claude/skills/delegate/SKILL.md').read_text())
        finally:
            release.touch()
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_explicit_project_destination(self):
        self.install('--dest', str(self.repo / '.claude'))
        self.assertTrue((self.repo / '.claude/skills/delegate/SKILL.md').is_file())
        self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
