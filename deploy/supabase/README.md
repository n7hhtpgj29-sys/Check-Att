# Supabase Attendance V2 setup

Project: gryvdxrrgfskmgoqffhn

1. In Supabase SQL Editor, paste and run `deploy/supabase/001_attendance_v2.sql`. This creates only the private `attendance_v2` schema; public tables remain untouched.
2. Check using SQL: `SELECT table_name FROM information_schema.tables WHERE table_schema='attendance_v2' ORDER BY table_name;` (expect 5 tables).
3. No roster or credentials are committed. Import roster through authenticated server application after deployment.
4. Keep DATABASE_URL in Render service environment variables only, never in source or browser. Configure SSL for PostgreSQL. Verify the connection supports the dedicated schema and has least-privilege grants.
5. Deploy a separate Render V2 staging service from feature/v2-vps-migration. Do not alter the existing main/production service.
6. Schedule times: 08:15 Day, 20:15 Night, timezone Asia/Bangkok. Manual runs can occur any time; scheduled_key ensures no duplicate scheduled run per department/shift/date.
7. Only NO_SCAN_IN_WINDOW results from a completed, sufficiently complete run are missing candidates. QUERY_ERROR and INCOMPLETE must not be reported as missing. Leave/holiday approval is a separate business process.
8. This is database groundwork, not a deployed collector or scheduler. The current app uses existing Store tables in public/SQLite; wiring it to attendance_v2 requires separate application changes. Do not point the production app to this schema.
