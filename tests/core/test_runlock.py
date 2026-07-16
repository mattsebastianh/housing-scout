"""Tests for the cross-process pidfile run lock."""

import os
import subprocess
import sys

import pytest

from scout.core import runlock


def test_acquire_writes_own_pid(tmp_path):
    """Acquiring the lock creates a pidfile holding the current process id."""
    lock = tmp_path / "run.lock"
    runlock.acquire(lock)
    assert int(lock.read_text()) == os.getpid()


def test_second_acquire_raises_lock_held(tmp_path):
    """A second acquire against a live holder raises LockHeld."""
    lock = tmp_path / "run.lock"
    runlock.acquire(lock)
    with pytest.raises(runlock.LockHeld):
        runlock.acquire(lock)


def test_release_removes_lockfile(tmp_path):
    """Releasing deletes the pidfile so the next acquire succeeds."""
    lock = tmp_path / "run.lock"
    runlock.acquire(lock)
    runlock.release(lock)
    assert not lock.exists()
    runlock.acquire(lock)  # no raise


def test_hold_releases_on_exception(tmp_path):
    """The hold() context manager releases the lock even when the body raises."""
    lock = tmp_path / "run.lock"
    with pytest.raises(RuntimeError):
        with runlock.hold(lock):
            assert lock.exists()
            raise RuntimeError("boom")
    assert not lock.exists()


def test_stale_lock_from_dead_process_is_reclaimed(tmp_path):
    """A pidfile left by a dead process does not block a new acquire."""
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    lock = tmp_path / "run.lock"
    lock.write_text(str(proc.pid))
    runlock.acquire(lock)  # reclaims the stale lock, no raise
    assert int(lock.read_text()) == os.getpid()


def test_is_locked_states(tmp_path):
    """is_locked is False when absent or stale, True while genuinely held."""
    lock = tmp_path / "run.lock"
    assert runlock.is_locked(lock) is False
    runlock.acquire(lock)
    assert runlock.is_locked(lock) is True
    runlock.release(lock)

    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()
    lock.write_text(str(proc.pid))
    assert runlock.is_locked(lock) is False
