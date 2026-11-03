"""Conservative Git change protection. This does not create an execution sandbox."""
import hashlib
import os
from pathlib import Path
import subprocess
import shutil

from .safety import SafetyError, canonical, within


def git_command(workspace):
    """Guard before every inspection: Git clean filters can execute during diff/status."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_NO_REPLACE_OBJECTS="1")
    executable = shutil.which("git", path=os.defpath)
    if not executable:
        raise SafetyError("Git is unavailable on the system executable path")
    command = [executable, "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull,
               "-c", "core.untrackedCache=false", "-c", "protocol.allow=never", "--no-optional-locks"]
    guard = subprocess.run(command + ["config", "--includes", "--name-only", "--get-regexp", r"^filter\..*\.(clean|process|smudge)$"],
                           cwd=str(workspace), env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    if guard.returncode != 1:
        raise SafetyError("Git filters configured or configuration unreadable; inspection refused before executing repository code")
    return command, env


def git(workspace, *args):
    command, env = git_command(workspace)
    result = subprocess.run(command + list(args), cwd=str(workspace), env=env, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
    if result.returncode or len(result.stdout) > 8*1024*1024:
        raise SafetyError("Git protection check failed or exceeded output limit")
    return result.stdout


def fingerprint(workspace, clean=False):
    workspace = canonical(workspace)
    root = canonical(os.fsdecode(git(workspace, "rev-parse", "--show-toplevel")).strip())
    if root != workspace:
        raise SafetyError("live writes require the exact Git worktree root")
    branch = git(workspace, "symbolic-ref", "--short", "HEAD").decode().strip()
    if not branch.startswith("superagent/") or branch in ("main", "master", "trunk"):
        raise SafetyError("live writes require a dedicated superagent/* branch, never a protected/existing work branch")
    status = git(workspace, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=all")
    if clean and status:
        raise SafetyError("workspace has existing changes; prepare a clean dedicated worktree without resetting user work")
    digest = hashlib.sha256()
    for data in (git(workspace, "rev-parse", "HEAD"), branch.encode(), status,
                 git(workspace, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--ignore-submodules=all", "HEAD"),
                 git(workspace, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--binary", "--ignore-submodules=all", "HEAD")):
        digest.update(data + b"\0")
    total = 0
    for name in git(workspace, "ls-files", "--others", "--exclude-standard", "-z").split(b"\0"):
        if not name:
            continue
        target = canonical(workspace / os.fsdecode(name))
        if not within(target, workspace) or not target.is_file():
            raise SafetyError("untracked path is not a safe regular file")
        total += target.stat().st_size
        if total > 8*1024*1024:
            raise SafetyError("untracked snapshot byte cap exceeded")
        digest.update(name + b"\0" + target.read_bytes())
    return digest.hexdigest()


def review_context(workspace, stamp):
    import json
    value = {"workspace_stamp": stamp, "head": git(workspace, "rev-parse", "HEAD").decode().strip(),
             "branch": git(workspace, "symbolic-ref", "--short", "HEAD").decode().strip(),
             "status": git(workspace, "status", "--porcelain=v1", "--untracked-files=all", "--ignore-submodules=all").decode("utf-8", "replace"),
             "diff": git(workspace, "diff", "--no-ext-diff", "--no-textconv", "--binary", "--ignore-submodules=all", "HEAD").decode("utf-8", "replace"),
             "note": "Untracked contents are not in the Git diff; inspect listed files within approved paths."}
    body = json.dumps(value, ensure_ascii=True, sort_keys=True)
    if len(body.encode()) > 131072:
        raise SafetyError("change context exceeds 128 KiB; split/narrow work before review")
    return body


def enforce_changed_paths(workspace, paths):
    """Detect out-of-scope tracked/deleted/renamed/untracked changes before acceptance.

    This is an after-the-fact gate, not a sandbox or rollback. Ignored files and
    submodule internals require external isolation/review.
    """
    names = set()
    for data in (git(workspace, "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "--ignore-submodules=all", "HEAD"),
                 git(workspace, "diff", "--cached", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z", "--ignore-submodules=all", "HEAD"),
                 git(workspace, "ls-files", "--others", "--exclude-standard", "-z")):
        names.update(os.fsdecode(name) for name in data.split(b"\0") if name)
    for name in names:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or not any(within(path, Path(allowed)) for allowed in paths):
            raise SafetyError("changed path outside approved scope: " + name)
