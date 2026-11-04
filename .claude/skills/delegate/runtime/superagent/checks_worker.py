"""Fixed checks. Project test code runs only in a no-network credential-free container."""
import json
import os
from pathlib import Path
import re
import subprocess
import shutil
import sys

# Executed by absolute trusted bundle path with Python -I -B, never caller imports.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from superagent.workspace import git_command

UNITTEST = """import unittest,sys,os,json
sys.path.insert(0,os.getcwd())
suite=unittest.defaultTestLoader.discover('tests')
count=suite.countTestCases()
if not count:
 print(json.dumps({'discovered':0,'error':'No tests discovered'}));sys.exit(2)
result=unittest.TextTestRunner(verbosity=2).run(suite)
print(json.dumps({'discovered':count,'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors)}))
sys.exit(not result.wasSuccessful())
"""
GIT_CHECK = [shutil.which("git", path=os.defpath) or "/nonexistent/git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
             "--no-optional-locks", "diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD"]


def command_for(check, image, workspace, docker="docker", container=None):
    if check == "git-diff-check":
        return GIT_CHECK
    if check != "python-unittest" or not isinstance(image, str) or not re.fullmatch(r"[A-Za-z0-9./_-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("project tests require an approved digest-pinned preinstalled check image")
    if os.getuid() == 0:
        raise ValueError("container test execution requires a non-root operator; never chmod user source to compensate")
    # No image download, credentials, home/state/socket mounts, network or writable source mount.
    # The operator must have approved this existing image and Docker access beforehand.
    if not isinstance(container, str) or not re.fullmatch(r"superagent-[a-f0-9]{32}", container):
        raise ValueError("container requires an owned attempt ID")
    return [docker, "--host", "unix:///var/run/docker.sock", "run", "--name", container,
            "--label", "com.superagent.attempt=" + container, "--rm", "--pull=never", "--network=none", "--read-only",
            "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=128", "--memory=512m", "--cpus=1",
            "--user=" + str(os.getuid()) + ":" + str(os.getgid()), "--tmpfs=/tmp:rw,nosuid,nodev,mode=1777,size=64m", "--workdir=/workspace",
            "--mount", "type=bind,source=" + str(workspace) + ",target=/workspace,readonly",
            "--entrypoint", "python3", image, "-I", "-B", "-c", UNITTEST]


def main():
    spec = json.loads(sys.stdin.read(65536))
    if set(spec) != {"checks", "check_image", "docker", "container"} or not isinstance(spec["checks"], list) or not 1 <= len(spec["checks"]) <= 4:
        raise ValueError("invalid check request")
    workspace = Path.cwd().resolve()
    if "," in str(workspace) or "\n" in str(workspace):
        raise ValueError("workspace is not representable as a safe container mount")
    evidence = []
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "TZ", "SYSTEMROOT")}
    env.update(HOME="/nonexistent", GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", PYTHONDONTWRITEBYTECODE="1")
    for check in spec["checks"]:
        command = command_for(check, spec["check_image"], workspace, spec["docker"], spec["container"])
        if check == "git-diff-check":
            prefix, env = git_command(workspace)
            command = prefix + ["diff", "--no-ext-diff", "--no-textconv", "--check", "HEAD"]
        proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env)
        output = bytearray()
        overflow = False
        while True:
            data = proc.stdout.read(8192)
            if not data:
                break
            if len(output) + len(data) > 65536:
                overflow = True
                proc.kill()
                break
            output.extend(data)
        proc.stdout.close()
        code = proc.wait()
        test_counts = None
        if check == "python-unittest":
            for line in output.decode("utf-8", "replace").splitlines():
                try:
                    candidate = json.loads(line)
                    if isinstance(candidate, dict) and set(candidate) == {"discovered", "run", "failures", "errors"}:
                        test_counts = candidate
                except ValueError:
                    pass
            if not test_counts or type(test_counts["run"]) is not int or test_counts["run"] <= 0 or test_counts["discovered"] != test_counts["run"] or test_counts["failures"] or test_counts["errors"]:
                code = code or 2
        evidence.append({"check": check, "command": command, "exit_code": code,
                         "passed": code == 0 and not overflow, "output": output.decode("utf-8", "replace"),
                         "output_limit_exceeded": overflow, "test_counts": test_counts})
        if not evidence[-1]["passed"]:
            break
    print(json.dumps({"type": "check_result", "passed": all(e["passed"] for e in evidence), "evidence": evidence}))


if __name__ == "__main__":
    main()
