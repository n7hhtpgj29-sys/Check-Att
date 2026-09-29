# V12.1.3 — test record

## Executed in this build session

- `pytest -q --disable-warnings`: **125 passed**.
- `python -m compileall`: passed.
- `node --check static/shift_views.js`: passed.
- Browser UI test: Chromium executable `/usr/bin/chromium`.
- Viewports: 390×844 and 1366×900.
- Browser timezone: America/Los_Angeles; simulated server clock: 2026-09-29 08:30 Asia/Bangkok.
- No page JavaScript errors in the tested flow.

## Coverage

Four mode/date mappings, UTC-to-Thai rollover, leap day/year boundary, naive-clock rejection,
24-hour format validation, unknown versus empty roster, Excel shift/department/resignation changes,
transaction rollback, historical no-data semantics, stale manual-date rejection, migrated old schedules,
unsaved schedule isolation, etag conflicts, validation all-or-nothing, atomic parallel claims,
same-time idempotence, revision on changed time, correct next run after completion, Sunday morning/night rule,
late tick crossing midnight, authenticated/pinned AUTO launch, shared job duplicate protection,
persisted progress/timing, archive export/add-only restore, actual worker body with mock browser,
legacy current-day cache safety, restart persistence and manual-versus-scheduled heartbeat.

Inherited master/persistence regressions remain included. Version expectation and release workflow checksum
assertions were updated for this version. The workflow intentionally changes payload/authentication;
its GitHub cadence and concurrency group remain unchanged, covered by a separate semantic assertion.

## What this does NOT certify

Flask and psycopg/PostgreSQL could not be installed in this offline environment. Existing Flask route test
doubles invoke the real application route bodies with a real local SQLite database. The browser test uses
inlined static resources and mock fetch calling those route bodies, not a deployed Flask application.
Playwright/MIS requests were replaced by test doubles. No live Supabase, Render, GitHub runs or actual
employee records were modified. Safari on a physical iPhone was not tested.

Do not label these as production/real-PostgreSQL end-to-end tests. After deployment, verify health flags,
previously saved department names, restored schedule times, an actual scheduled GitHub run, and the
first saved roster day before relying on historical views.
