"""Read-only attendance collector; same fresh-page query lifecycle as Production PWA.

Do not turn source/browser errors or absent unverified rows into No Scan.
"""
from datetime import datetime, timedelta, time as clock
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
from collector_v2 import SOURCE
import logging
import re
import time

log = logging.getLogger(__name__)
BKK = ZoneInfo("Asia/Bangkok")
DATE_TIME = re.compile(r"(\d{1,2}/\d{1,2}/\d{4})\s*(\d{1,2}:\d{2}(?::\d{2})?)")


def _parse_scan(value):
    """Accept date/time badges, extra whitespace, or milliseconds in new table UI."""
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    match = DATE_TIME.search(s)
    if not match:
        return None
    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            return datetime.strptime(match.group(1) + " " + match.group(2), fmt)
        except ValueError:
            pass
    return None


def _read_matching_records(page, employee_no, timeout=10):
    deadline = time.monotonic() + timeout
    saw_employee = False
    last_dom_error = None
    while time.monotonic() < deadline:
        try:
            # The newer source uses AJAX and pagination. Read visible table text,
            # preserving whitespace between its date/time badges.
            rows = page.locator("table tbody tr").evaluate_all(
                """rows => rows.map(row =>
                    Array.from(row.querySelectorAll('td'), cell =>
                        (cell.innerText || cell.textContent || '').trim()))"""
            )
            records = []
            for values in rows:
                if len(values) < 4 or str(values[1]).strip().upper() != employee_no.upper():
                    continue
                saw_employee = True
                parsed = _parse_scan(values[3])
                if parsed is not None:
                    records.append(parsed)
            if records:
                return "OK", records
        except Exception as exc:
            # AJAX might be replacing the DOM while this snapshot is being read.
            last_dom_error = type(exc).__name__
        page.wait_for_timeout(300)
    if saw_employee:
        return "BAD_TIMESTAMP_FORMAT", []
    if last_dom_error:
        log.warning("V2 collector DOM read transient failure: %s", last_dom_error)
    return "NO_VERIFIED_ROWS", []


def _one_query(page, employee_no, shift, day, refresh_page=True, read_timeout=7):
    # Production PWA navigates afresh for EACH employee. Reusing the same page
    # made old V2 vulnerable to stale AJAX state and missing submit controls.
    if refresh_page:
        response = page.goto(SOURCE, wait_until="domcontentloaded", timeout=12000)
        if response is None or response.status != 200:
            return "QUERY_ERROR", "SOURCE_HTTP_ERROR"
    field = page.locator("input").first
    field.wait_for(state="visible", timeout=5000)
    field.fill(employee_no, timeout=4000)
    go = page.get_by_role("button", name=re.compile(r"^\s*GO\s*$", re.I))
    try:
        if go.count():
            go.first.click(timeout=5000, no_wait_after=True)
        elif page.locator("input[type=submit]").count():
            page.locator("input[type=submit]").first.click(timeout=5000, no_wait_after=True)
        else:
            # Works for source variants with a search field but no GO button.
            field.press("Enter", timeout=5000)
    except Exception as exc:
        # Production continues reading when a click fails: AJAX may already
        # have submitted, or the source may update on input.
        log.warning("V2 collector submit issue: %s", type(exc).__name__)

    reason, found = _read_matching_records(page, employee_no, timeout=read_timeout)
    if not found:
        return ("QUERY_ERROR" if reason == "BAD_TIMESTAMP_FORMAT" else "INCOMPLETE"), reason

    if shift == "D":
        matched = [x for x in found if x.date() == day and x.time() < clock(12)]
    else:
        begin = datetime.combine(day, clock(16))
        end = datetime.combine(day + timedelta(days=1), clock(12))
        matched = [x for x in found if begin <= x <= end]

    if matched:
        return "SCAN_FOUND", "VERIFIED_SCAN"
    shift_start = datetime.combine(day, clock(8 if shift == "D" else 20), BKK)
    if datetime.now(BKK) >= shift_start:
        return "NO_SCAN_IN_WINDOW", "VERIFIED_HISTORICAL_ROWS_NO_SHIFT_SCAN"
    return "INCOMPLETE", "SHIFT_NOT_STARTED"


def scan_group(ids, shift, work_date, progress_callback=None, result_callback=None, resumed=None):
    """Yield exactly one of the four existing statuses for every employee.

    The job runner persists no-scan reports only when the entire query is
    complete and there are zero QUERY_ERROR/INCOMPLETE results.
    """
    day = datetime.strptime(work_date, "%Y-%m-%d").date()
    # Keep a result slot for every employee until all retry passes complete.
    restored = resumed or {}
    outcomes = [restored.get(emp) if restored.get(emp) in ("SCAN_FOUND","NO_SCAN_IN_WINDOW") else "INCOMPLETE" for emp in ids]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"])
        try:
            context = browser.new_context(
                ignore_https_errors=True, locale="en-US",
                timezone_id="Asia/Bangkok",
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/140.0.0.0 Safari/537.36")
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
            page = context.new_page()
            allow_reuse = True
            reuse_failures = 0
            times = []
            # First pass: fast AJAX query where verified, then fresh-page retry.
            # Never synthesize QUERY_ERROR for people not yet queried.
            for i, employee_no in enumerate(ids):
                if restored.get(employee_no) in ("SCAN_FOUND","NO_SCAN_IN_WINDOW"):
                    if progress_callback:
                        progress_callback(stage="first_pass",checked=i+1,total=len(ids),
                            retry_pending=sum(x in ("QUERY_ERROR","INCOMPLETE") for x in outcomes[:i+1]))
                    continue
                started = time.monotonic()
                result, reason = "INCOMPLETE", "NO_VERIFIED_ROWS"
                for attempt in range(2):
                    reuse = (attempt == 0 and i > 0 and allow_reuse)
                    try:
                        result, reason = _one_query(
                            page, employee_no, shift, day,
                            refresh_page=not reuse,
                            read_timeout=5 if reuse else 15)
                    except Exception as exc:
                        result, reason = "QUERY_ERROR", type(exc).__name__
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = context.new_page()
                    if result in ("SCAN_FOUND", "NO_SCAN_IN_WINDOW"):
                        if reuse:
                            reuse_failures = 0
                        break
                    if reuse:
                        reuse_failures += 1
                        if reuse_failures >= 3:
                            allow_reuse = False
                    if attempt == 0:
                        page.wait_for_timeout(350)
                outcomes[i] = result
                if result_callback:
                    result_callback(employee_no,result,"first_pass")
                if progress_callback:
                    progress_callback(stage="first_pass", checked=i + 1,
                                      total=len(ids), retry_pending=sum(s in ("QUERY_ERROR", "INCOMPLETE") for s in outcomes[:i+1]))
                if result in ("QUERY_ERROR", "INCOMPLETE"):
                    log.warning("V2 initial scan unverified index=%d reason=%s status=%s",
                                i + 1, reason, result)
                times.append(time.monotonic() - started)
                if (i + 1) % 10 == 0 or i + 1 == len(ids):
                    recent = times[-10:]
                    log.info("V2 first pass %d/%d avg_last_10=%.2fs pending=%d",
                             i + 1, len(ids), sum(recent)/len(recent),
                             sum(s in ("QUERY_ERROR", "INCOMPLETE") for s in outcomes[:i+1]))
                page.wait_for_timeout(120)

            # Second phase: retry ONLY unverified employees using a fresh page.
            # No successful employee is queried again within this job.
            for retry_round in (1, 2):
                pending = [i for i, status in enumerate(outcomes)
                           if status in ("QUERY_ERROR", "INCOMPLETE")]
                if not pending:
                    break
                log.info("V2 retry pass %d pending=%d", retry_round, len(pending))
                if progress_callback:
                    progress_callback(stage="retry_"+str(retry_round), checked=len(ids),
                                      total=len(ids), retry_pending=len(pending))
                # Small cooldown prevents immediate overload when source is slow.
                page.wait_for_timeout(2000)
                for i in pending:
                    employee_no = ids[i]
                    try:
                        result, reason = _one_query(
                            page, employee_no, shift, day,
                            refresh_page=True, read_timeout=20)
                    except Exception as exc:
                        result, reason = "QUERY_ERROR", type(exc).__name__
                        try:
                            page.close()
                        except Exception:
                            pass
                        page = context.new_page()
                    outcomes[i] = result
                    if result_callback:
                        result_callback(employee_no,result,"retry_"+str(retry_round))
                    if result in ("QUERY_ERROR", "INCOMPLETE"):
                        log.warning("V2 retry pass=%d index=%d reason=%s status=%s",
                                    retry_round, i + 1, reason, result)
                    page.wait_for_timeout(300)

            for result in outcomes:
                yield result
            context.close()
        finally:
            browser.close()
