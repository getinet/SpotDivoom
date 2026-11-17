"""
Tiny change-notification bus between the daemon and the web dashboard's live stream.

The daemon calls publish() whenever something the dashboard shows has changed; each
open /api/events stream blocks in wait_for_change() and sends a fresh status when woken.
"""

import threading

_cond = threading.Condition()
_version = 0


def publish() -> None:
    global _version
    with _cond:
        _version += 1
        _cond.notify_all()


def current_version() -> int:
    return _version


def wait_for_change(seen_version: int, timeout: float) -> int:
    """
    Blocks until the version moves past `seen_version` or `timeout` passes; returns the version.
    """
    with _cond:
        _cond.wait_for(lambda: _version != seen_version, timeout=timeout)
        return _version
