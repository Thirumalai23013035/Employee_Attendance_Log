# DECISIONS.md

1. **Indexes.** A unique `employees.emp_code` index prevents duplicate employee identities. A unique `(emp_code, date)` attendance index guarantees one record per employee/day. Department/join-date and attendance date/employee indexes support headcount, list, monthly, and lookup queries. I did not add a unique email index because the contract only guarantees `emp_code` uniqueness.

2. **Punch-in race.** Both requests may check that the employee exists, but neither relies on a duplicate pre-check. MongoDB enforces the unique `(emp_code, date)` index during insert. One request succeeds with `201`; the other receives a duplicate-key error and becomes `409`.

3. **Ties.** `$rank` uses total late minutes, so tied employees share a rank and the next rank is skipped. I filter on `rank <= limit` after ranking, then order tied rows by `emp_code`. The result can contain more than `limit` employees.

4. **Headcount.** Department summary starts with employees who joined by month end and looks up their logs. Employees with no logs still count, while future joiners are excluded.

5. **100x data.** I would load-test realistic data, inspect explain plans and cardinalities, then consider pre-aggregated daily summaries and workload-specific indexes rather than repeatedly calculating long reporting windows.
