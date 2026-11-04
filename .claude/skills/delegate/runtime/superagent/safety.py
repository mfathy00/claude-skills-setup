"""Input and filesystem checks, not a substitute for worker sandboxing."""
import json
import os
from pathlib import Path
import re
import stat


class SafetyError(ValueError):
    pass


def identifier(value, label="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", value):
        raise SafetyError("invalid " + label)
    return value


def bounded_text(value, label, limit=16384):
    if not isinstance(value, str) or not value.strip() or len(value.encode("utf-8")) > limit or "\x00" in value:
        raise SafetyError("invalid or oversized " + label)
    return value


def integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise SafetyError("invalid " + label)
    return value


def canonical(path, must_exist=True):
    """Reject traversal and symlinks before resolving, including parent links."""
    path = Path(path).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise SafetyError("use an absolute path without '..'")
    for node in [path] + list(path.parents):
        if node.is_symlink():
            raise SafetyError("symlink path refused: " + str(node))
    if must_exist and not path.exists():
        raise SafetyError("path does not exist: " + str(path))
    return path.resolve(strict=must_exist)


def within(path, root):
    return path == root or root in path.parents


def private_directory(path, create=False):
    path = canonical(path, must_exist=not create)
    if create:
        path.mkdir(mode=0o700, parents=False, exist_ok=True)
    mode = path.stat()
    if not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.getuid() or mode.st_mode & 0o077:
        raise SafetyError("state directory must be owned by you with mode 0700")
    return path


def private_file(path, missing_ok=False):
    path = canonical(path, must_exist=not missing_ok)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
        raise SafetyError("state files must be private, regular, single-link files")
    return path


def read_json(path, max_bytes=65536, with_size=False):
    path = canonical(path)
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise SafetyError("JSON input must be a bounded regular file")
    def reject(value):
        raise SafetyError("non-finite JSON number")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SafetyError("duplicate JSON field: " + key)
            result[key] = value
        return result
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise SafetyError("JSON input must be a regular single-link file")
        data = handle.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SafetyError("JSON input grew beyond byte limit")
    try:
        value = json.loads(data.decode("utf-8"), parse_constant=reject, object_pairs_hook=pairs)
        return (value, len(data)) if with_size else value
    except RecursionError as exc:
        raise SafetyError("JSON nesting exceeds parser limit") from exc


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def scope_path(value, workspace):
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise SafetyError("invalid scope path")
    path = Path(value)
    if not path.parts or path.is_absolute() or any(p in ("..", ".git", ".claude", ".codex", ".agents", ".superagent") for p in path.parts):
        raise SafetyError("scope must be relative and exclude agent/config/Git state")
    target = canonical(workspace / path, must_exist=False)
    if not within(target, workspace):
        raise SafetyError("scope escapes workspace")
    return path.as_posix()


def overlap(a, b):
    a, b = Path(a), Path(b)
    return within(a, b) or within(b, a)
