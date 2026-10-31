"""Start opt-in scheduler and durable job recovery after Gunicorn worker starts.

Single worker only, preserving existing V2 in-memory progress interface.
"""
import logging
from threading import Thread

log=logging.getLogger(__name__)


def _repair():
    try:
        from group_runner import recover_interrupted_jobs
        recover_interrupted_jobs()
        from webhook_bridge import reconcile_completed
        log.info("V2 webhook reconciliation result: %s",reconcile_completed())
    except Exception:
        log.exception("V2 recovery / webhook reconciliation failed")


def post_worker_init(worker):
    from scheduler_v2 import start
    start()
    Thread(target=_repair,name="v2-recovery",daemon=True).start()
