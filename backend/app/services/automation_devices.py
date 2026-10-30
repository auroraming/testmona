"""Device lock and offline reclaim.

Locks are explicit. A device that misses its heartbeat is marked offline and
its lock is cleared so a disconnected worker cannot hold a device forever.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


OFFLINE_AFTER = timedelta(seconds=90)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def lock_is_active(device: Any, now: datetime) -> bool:
    expires = _as_utc(getattr(device, "lock_expires_at", None))
    return bool(getattr(device, "lock_task_id", None) and expires and expires > now)


def apply_offline_reclaim(device: Any, now: datetime, offline_after: timedelta = OFFLINE_AFTER) -> bool:
    """Mark a stale device offline and drop its lock. Return True when a change was made."""
    seen = _as_utc(getattr(device, "last_seen_at", None))
    stale = seen is None or seen <= now - offline_after
    expired_lock = device.lock_task_id is not None and not lock_is_active(device, now)
    if not stale and not expired_lock:
        return False
    changed = False
    if stale and device.status != "offline":
        device.status = "offline"
        changed = True
    elif (not stale) and device.status == "locked":
        device.status = "online"
        changed = True
    if device.lock_task_id is not None or device.lock_runner_id is not None or device.lock_expires_at is not None:
        device.lock_task_id = None
        device.lock_runner_id = None
        device.lock_expires_at = None
        changed = True
    return changed


def acquire_lock(device: Any, *, task_id: int, runner_id: int, now: datetime, lease: timedelta = OFFLINE_AFTER) -> None:
    if device.status == "offline":
        raise PermissionError("Device is offline")
    if lock_is_active(device, now) and device.lock_task_id != task_id:
        raise PermissionError("Device is locked by another task")
    device.status = "locked"
    device.lock_task_id = task_id
    device.lock_runner_id = runner_id
    device.lock_expires_at = now + lease
    device.last_seen_at = now


def release_lock(device: Any, *, task_id: int, runner_id: int) -> bool:
    """Release a lock held by this task and runner. Repeat calls are idempotent."""
    if device.lock_task_id is None:
        return False
    if device.lock_task_id != task_id or device.lock_runner_id != runner_id:
        raise PermissionError("Device lock is held by another runner")
    device.lock_task_id = None
    device.lock_runner_id = None
    device.lock_expires_at = None
    if device.status == "locked":
        device.status = "online"
    return True
