# Cal-Comp attendance source contract (observed 2026-10-16)

Evidence: user's Chrome DevTools Network screenshots for employee C170493. This is **not** a verified server-side HTTP test.

- Endpoint shown: `index.php` on the Cal-Comp attendance site; full Request URL and HTTP method **not yet confirmed** (inspect Network > Headers).
- Request payload is form data: `search_emp=C170493`, `limit=20`, `offset=0`.
- JSON response has `total` and `rows`. Example:
```json
{"total":91,"rows":[{"id":"C170493","name":"NIWAT","time":"16/10/2026 07:38:11"},{"id":"C170493","name":"NIWAT","time":"16/10/2026 07:38:08"}]}
```
- Dates are `DD/MM/YYYY HH:mm:ss` in local factory time (confirm timezone); duplicate scans can occur within seconds.
- `total=91` while `limit=20`: do not mistake page 1 for full history; page until sufficient shift-window coverage or exhaustion. Cap pages and query time.
- The endpoint is intended for an employee lookup; confirm authorization, usage constraints, network accessibility and whether a session cookie is required. Do not copy cookies, CSRF tokens, credentials or browser session headers into GitHub.
- Never classify a person MISSING on timeout, HTTP error, invalid JSON, truncated pagination, authentication redirect or partial source results. Mark QUERY_FAILED/INCOMPLETE instead.
- Match expected roster and assigned shift first; a qualifying scan means PRESENT internally, but public dashboard returns **missing employees only**. Night shift can cross midnight. Dedupe near-identical scans and persist provenance without logging personal data unnecessarily.

## Next checks
1. Inspect Headers > General for exact Request URL and method (redact sensitive values).
2. Implement `AttendanceSourceClient` using authorized form POST only if method is POST, or appropriate actual method; fallback to Playwright if the site requires a browser session.
3. Test on one authorized ID, then add paginated contract tests and a missing-only integration test.
