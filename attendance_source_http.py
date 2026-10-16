"""Read-only Cal-Comp attendance source adapter.

Do not classify missing from an incomplete/failed lookup.
Requires authorization to access the corporate attendance endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
import requests

DEFAULT_URL = "https://webapp.calcomp.co.th/att/index.php"
DATE_FORMAT = "%d/%m/%Y %H:%M:%S"


class AttendanceSourceError(RuntimeError):
    pass


def fetch_employee_scans(
    employee_id: str,
    *,
    url: str = DEFAULT_URL,
    session: requests.Session | None = None,
    limit: int = 20,
    max_pages: int = 10,
    timeout: int = 15,
) -> dict[str, Any]:
    """Fetch all available pages up to a hard cap; raise on incomplete results.

    Returns {employee_id, total, rows}. The caller must apply shift windows
    and roster rules; an empty successful response is not by itself absence.
    """
    employee_id = employee_id.strip().upper()
    if not employee_id or not employee_id.isalnum():
        raise ValueError("Invalid employee ID")
    if not 1 <= limit <= 100 or max_pages < 1:
        raise ValueError("Invalid pagination limits")
    client = session or requests.Session()
    rows: list[dict[str, str]] = []
    total: int | None = None
    for page in range(max_pages):
        try:
            response = client.post(
                url,
                data={"limit": limit, "offset": page * limit, "search_emp": employee_id},
                timeout=timeout,
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://webapp.calcomp.co.th/att/",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AttendanceSourceError("Attendance lookup failed") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise AttendanceSourceError("Unexpected attendance response")
        page_total = payload.get("total")
        if type(page_total) is not int or page_total < 0:
            raise AttendanceSourceError("Invalid attendance total")
        if total is None:
            total = page_total
        elif total != page_total:
            raise AttendanceSourceError("Attendance result changed during pagination")
        page_rows = payload["rows"]
        if len(page_rows) > limit:
            raise AttendanceSourceError("Page exceeded requested limit")
        for row in page_rows:
            if not isinstance(row, dict) or not all(k in row for k in ("id", "name", "time")):
                raise AttendanceSourceError("Malformed attendance row")
            if str(row["id"]).strip().upper() != employee_id:
                raise AttendanceSourceError("Employee mismatch in source response")
            try:
                datetime.strptime(str(row["time"]), DATE_FORMAT)
            except ValueError as exc:
                raise AttendanceSourceError("Invalid scan timestamp") from exc
            rows.append({k: str(row[k]) for k in ("id", "name", "time")})
        if len(rows) >= total:
            if len(rows) != total:
                raise AttendanceSourceError("Unexpected result count")
            return {"employee_id": employee_id, "total": total, "rows": rows}
        if not page_rows:
            raise AttendanceSourceError("Pagination ended before total was reached")
    raise AttendanceSourceError("Pagination cap reached; incomplete attendance lookup")
