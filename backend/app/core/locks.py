"""Shared process-local locks for task orchestration.

These locks are intentionally per-process (not distributed). They protect the
race window between "check for an active task" and "insert a new task" within a
single API call or synchronous agent run.
"""

from __future__ import annotations

import threading


_TASK_LOCKS: dict[str, threading.Lock] = {}
_TASK_LOCKS_GUARD = threading.Lock()


def get_session_task_lock(session_id: str, task_type: str) -> threading.Lock:
    """Return a per-(session_id, task_type) lock.

    The lock is created lazily and cached for the lifetime of the process.
    """
    key = f"{session_id}:{task_type}"
    lock = _TASK_LOCKS.get(key)
    if lock is None:
        with _TASK_LOCKS_GUARD:
            lock = _TASK_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                _TASK_LOCKS[key] = lock
    return lock
