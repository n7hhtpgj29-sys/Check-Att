"""Gunicorn hooks for the opt-in V2 Bangkok scheduler.

Only one worker is supported for the existing in-memory collector. Scheduler
is inactive unless V2_INTERNAL_SCHEDULER_ENABLED=1 is set explicitly.
"""
def post_worker_init(worker):
    from scheduler_v2 import start
    start()
