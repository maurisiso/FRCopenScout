"""
Run slow API syncs in a background thread so pages never wait for TBA/Statbotics.

A cache "lock" makes sure the same job isn't started twice at the same time
(e.g. three scouts opening the event page at once).

This is enough for one server process (your PC, a small deployment). For a
bigger deployment we'd move these jobs to a task queue (Celery / RQ).
"""
import logging
import threading

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections

log = logging.getLogger("frcdata")


def run_in_background(job_key, func, *args, lock_seconds=300, **kwargs):
    """Start func(*args) in a thread unless the same job_key is already running. Returns True if started."""
    if not cache.add(f"job:{job_key}", True, lock_seconds):
        return False

    def runner():
        try:
            func(*args, **kwargs)
        except Exception:  # noqa: BLE001 - background job must never crash the server
            log.exception("background job %s failed", job_key)
        finally:
            cache.delete(f"job:{job_key}")
            close_old_connections()

    if getattr(settings, "SYNC_IN_BACKGROUND", True):
        threading.Thread(target=runner, name=f"sync-{job_key}", daemon=True).start()
    else:  # tests run jobs inline so results are predictable
        runner()
    return True
