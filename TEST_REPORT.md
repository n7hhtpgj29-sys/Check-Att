# V12.1.1 Data Persistence Fix — Validation

Base: V12.1 deployed app.py Git blob 0d36ca55ba2d014f74453ebd5ac6e61f14c6085f.
GitHub V12.1 workflow kept byte-for-byte (Git blob cf1b50f0477d852e011cc52367b7878898d774d2).

## Passed here
- 32 offline tests using a real SQLite database and a Flask test double that invokes the application route bodies.
- Python syntax/compile checks for app.py, persistent_store.py, data_recovery.py.
- Node syntax checks for original inline app JS and new recovery JS.
- Chromium 390px offline DOM test: no automatic legacy Restore, preview, explicit recovery,
  added department appears, other departments retained, no page-level horizontal overflow, no JS errors.
  Browser API transport was mocked locally; screenshots used synthetic test employees.

## Not verified here
- Actual Flask server integration (Flask is not installed in this test runtime).
- Actual PostgreSQL, Supabase session pooler, Render deployment, iPhone Safari, or Cal-Comp MIS end-to-end.
- No production database data was read, migrated, or written by this build.

## Required before acceptance
1. Back up existing data before changing Render settings or deploying.
2. Configure a working PostgreSQL DATABASE_URL and REQUIRE_POSTGRES=true.
3. Health must report persistent_data/master/departments/schedule=true.
4. Import backups once and verify counts, names, departments, schedules.
5. Restart/redeploy the NEW version and confirm the same data remains without browser Restore.
6. Confirm the existing scheduled GitHub workflow still reads the saved department schedule.

This patch fixes the ephemeral-main-store and destructive-restore paths. It does not guarantee
against deliberate edits, compromised access, database deletion, provider outages, or lost backups.
