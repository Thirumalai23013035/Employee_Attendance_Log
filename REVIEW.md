# REVIEW.md

Defects found in the starter `app/main.py` and the corresponding fixes:

| # | Where | What is wrong | How to notice | Fix |
|---|---|---|---|---|
| 1 | `/health` | Always returned `200`, even if MongoDB was unavailable. | Stop MongoDB and request `/health`. | Run `ping`; return `503` on database errors. |
| 2 | `create_employee` | Duplicate check followed by insert is race-prone. | Send simultaneous creates with the same `emp_code`. | Unique database index; convert duplicate-key errors to `409`. |
| 3 | `EmployeeIn` | No format, length, email, date, or shift-time validation. Equal shift start/end was accepted. | Submit malformed codes, dates, email, or identical shift times. | Add Pydantic constraints and cross-field validation. |
| 4 | `create_employee` | `created_at` used a naive local datetime and was returned as a datetime instead of epoch milliseconds. | Inspect response and stored timestamp around timezone boundaries. | Store UTC-aware time and serialize instants to epoch milliseconds. |
| 5 | `list_employees` | `skip = page * page_size` skipped the first page; `total` ignored the department filter. | Request page 1 and a department filter. | Use `(page - 1) * page_size`; count with the same query. |
| 6 | `list_employees` | No pagination bounds or stable sort. | Pass page 0/negative size or compare pages across requests. | Validate page/page_size and sort by `emp_code`. |
| 7 | `punch_in` | Did not return `404` for unknown employees before dereferencing shift fields. | Punch in using an unknown code. | Check employee existence first. |
| 8 | `punch_in` | Check-then-insert allowed duplicate records under concurrent requests. | Send parallel requests for one employee/date. | Unique `(emp_code, date)` index and `409` on duplicate key. |
| 9 | `punch_in` | Used local naive timestamps and did not truncate to whole seconds or validate epoch-millisecond input. | Use timezone-boundary timestamps, seconds-looking values, floats, or strings. | Strict millisecond validation, UTC storage, whole-second truncation and IST attendance date. |
| 10 | `compute_late_minutes` | Did not correctly model overnight shifts and the strict 10-minute grace boundary. | Test 09:40:00, 09:40:01, and early-morning overnight punches. | Calculate shift start in IST and apply the strict >600-second rule. |
| 11 | `compute_overtime` | Assumed shift end was on the punch-in calendar date and did not enforce the 30-minute threshold. | Test an overnight shift and 29/30-minute overtime. | Calculate the actual shift end date and count only when at least 30 whole minutes late. |
| 12 | `/attendance` | Loaded all matching records into Python and sorted/sliced in memory. | Benchmark a large attendance collection. | Use indexed MongoDB filters, sort, skip/limit, and filtered count. |
| 13 | `/attendance` | Did not validate date range, status, or pagination and returned unstable ordering for ties. | Reverse date bounds or request invalid page values. | Validate inputs; sort by date descending and employee code ascending. |
| 14 | Work-hour calculation | Float rounding used Python's default rounding behavior, not explicit half-up rounding. | Test a duration exactly halfway between hundredths. | Use `Decimal` with `ROUND_HALF_UP`. |
| 15 | Missing implementation | Punch-out, regularization/audit history, four analytics endpoints, and explain endpoint were absent. | Call each contracted endpoint. | Implemented the endpoints and aggregation pipeline builders in this file. |
| 16 | Concurrent punch-out | A read-then-write flow alone can close one record twice. | Send simultaneous punch-outs for the same open record. | Conditional atomic update requiring `punch_out: null`; losing request gets `409`. |
| 17 | Regularization | Updating a record without compare-and-swap can lose another request's history entry. | Send concurrent corrections against the same record. | Conditional update compares the original mutable values; conflicts return `409`. |
| 18 | Indexes | The starter did not create query or uniqueness indexes at startup. | Inspect index list and explain plans. | Add idempotent unique and query-supporting indexes. |

Reviewed and retained: `emp_code` is the public natural key, while MongoDB `_id` stays internal; calendar dates remain `YYYY-MM-DD` strings as specified by the data model.
