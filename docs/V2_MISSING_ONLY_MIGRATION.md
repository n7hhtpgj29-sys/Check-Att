# Attendance PWA v2.0 — Missing-only VPS migration (Phase 1)

## Scope
- Keep Render production and main untouched.
- Check scheduled employees against the authorized Cal-Comp attendance website.
- Show **only employees without a qualifying scan-in** for their scheduled shift.
- Do not display present employee names or OT.
- Distinguish **MISSING**, **PENDING**, **QUERY_FAILED**, and **NOT_SCHEDULED**. A failed or incomplete source query must never count as missing.
- Day and night shifts are keyed by the shift **start date**; night-shift scans can occur on the following calendar day.
- Use Asia/Bangkok for shift interpretation and UTC timestamps for audit events.

## Existing implementation audit
- app.py: Flask routes, Playwright collection, in-process jobs and schedule APIs.
- persistent_store.py: PostgreSQL/SQLite adapter; PostgreSQL required for VPS.
- thai_schedule.py: per-department schedule rules, due-task claiming and contact diagnostics.
- .github/workflows/attendance-auto-query.yml: currently invokes /api/auto-query/tick and /api/query. Disable **only after** VPS scheduler is proven; avoid duplicate production collectors.
- Dockerfile: Playwright Python image, Gunicorn 1 worker/8 threads, Xvfb.
- Authentication: AUTO_QUERY_TOKEN guards scheduler calls, **not a substitute for user login/RBAC**. Audit every route before external exposure.

## Phase plan
1. Freeze a backup of Render DB and employee/department/shift settings; validate restore.
2. Implement new tables via migrations: employee_master, shift_assignments, collection_runs, scan_observations, missing_results, users and audit_events. Keep history and provenance; never overwrite without audit.
3. Implement source adapter with permitted access; inspect index.php method/payload/response in a secure environment. Prefer HTTP only if officially permitted; otherwise Playwright. Rate limit, bounded retries and redact personal data from logs.
4. Implement isolated worker, persistent idempotent claims with PostgreSQL INSERT ... ON CONFLICT DO NOTHING or transactional lease, stale lease recovery, per-department scheduling, and optional recheck.
5. Implement missing-only endpoints and authenticated frontend. For ChatGPT expose read-only, scoped summaries; avoid personal names by default.
6. Configure TLS reverse proxy and backups, verify tests, parallel-run against Render, cut over after approval.

## API target
- GET /api/v2/missing?department=PE&shift=DAY&work_date=YYYY-MM-DD
- GET /api/v2/missing/summary?work_date=YYYY-MM-DD
- GET /api/v2/scheduler/status
- POST /api/v2/admin/roster/import (admin only)
- POST /api/v2/admin/schedules (admin only)
Return only missing employee identifiers/names in the missing endpoint; never return present rosters. Include run status, freshness, and source errors.

## VPS deployment gate
The included Compose is a **private staging skeleton**, not a production deployment. It has no public port. Do not expose web until session authentication, department RBAC, HTTPS, CSRF protections, source authorization, backups, and security tests pass.
