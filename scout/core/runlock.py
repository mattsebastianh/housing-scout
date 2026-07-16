"""Cross-process pidfile lock so pipeline runs never overlap.

Both entry points take the same lock: ``run_daily.py`` (scheduled or manual)
acquires it around the pipeline, and the Telegram listener checks it before
dispatching an on-demand run. A lockfile left behind by a crashed process is
reclaimed automatically once its pid is dead.
"""

import os
from contextlib import contextmanager
from pathlib import Path


class LockHeld(Exception):
    """Another live process holds the run lock."""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _holder_pid(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def is_locked(path: Path) -> bool:
    """True while a live process holds the lock (stale pidfiles don't count)."""
    pid = _holder_pid(path)
    return pid is not None and _pid_alive(pid)


def acquire(path: Path) -> None:
    """Take the lock or raise LockHeld. Reclaims stale locks from dead pids."""
    for _ in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            pid = _holder_pid(path)
            if pid is not None and _pid_alive(pid):
                raise LockHeld(f"pid {pid} holds {path}")
            path.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as fh:
            fh.write(str(os.getpid()))
        return
    raise LockHeld(str(path))


def release(path: Path) -> None:
    path.unlink(missing_ok=True)


@contextmanager
def hold(path: Path):
    """Context manager: acquire on entry, always release on exit."""
    acquire(path)
    try:
        yield
    finally:
        release(path)
