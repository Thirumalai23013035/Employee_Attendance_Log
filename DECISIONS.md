# Design Decisions

## 1. Technology Stack

**Decision:** Use Python, FastAPI, and PyMongo with MongoDB.

**Rationale:** FastAPI provides request validation and automatic OpenAPI documentation. PyMongo provides direct access to MongoDB indexes, atomic updates, aggregation pipelines, and query execution plans.

**Trade-off:** Database operations and error handling require explicit implementation, but this gives control over the MongoDB behaviour evaluated by the assignment.

## 2. Application Structure

**Decision:** Keep the API implementation in `app/main.py`.

**Rationale:** The assignment specifies this application-code location and the startup command `uvicorn app.main:app --port 8000`.

**Trade-off:** A single application module is less modular than a multi-file architecture, so clear sections, reusable helper functions, and consistent naming are important.

## 3. Configuration and Secrets

**Decision:** Read `MONGO_URI` and `MONGO_DB` from environment variables.

**Rationale:** This separates environment-specific configuration from source code and prevents database credentials from being hardcoded.

**Trade-off:** Developers must configure their local environment before running the application. The repository includes placeholders in `.env.example`; real credentials remain in a local, uncommitted `.env` file.

## 4. Employee Identity

**Decision:** Use `emp_code` as the public business identifier and keep MongoDB `_id` internal.

**Rationale:** Employee codes are meaningful to API consumers and avoid exposing an implementation-specific database identifier.

**Trade-off:** Employee-code format and uniqueness must be enforced through validation and a database unique index.

## 5. Database Constraints and Concurrency

**Decision:** Enforce uniqueness using MongoDB indexes and use atomic operations for state-changing attendance requests.

**Rationale:** Application-level check-then-write sequences can fail when concurrent requests operate on the same data.

**Trade-off:** Duplicate-key errors and conditional-update failures must be handled explicitly. Conflicting requests should return the status code required by the API contract.

## 6. Attendance Record Identity

**Decision:** Use the employee code and attendance date as the attendance record's business identity, consistent with the supplied data model.

**Rationale:** This supports employee-day attendance lookups and prevents duplicate daily records.

**Trade-off:** The attendance date must be derived consistently, especially for overnight shifts.

## 7. Timezone and Timestamp Representation

**Decision:** Apply IST (UTC+05:30) for attendance business rules, store instants consistently as BSON datetimes, and serialize timestamps in the API format specified by the contract.

**Rationale:** Explicit timezone conversion avoids machine-local timezone differences and incorrect attendance dates.

**Trade-off:** Timestamp parsing and serialization require careful handling of epoch milliseconds, timezone-aware datetimes, and whole-second precision where required.

## 8. Overnight Shifts

**Decision:** Treat a shift that crosses midnight as a single logical shift spanning two calendar dates.

**Rationale:** Comparing shift start and end times on the same date can produce negative durations and incorrect late-arrival or overtime calculations.

**Trade-off:** Shift-end dates must be calculated explicitly, and boundary cases require dedicated tests.

## 9. Late-Arrival and Overtime Rules

**Decision:** Centralize attendance calculations and implement the exact grace-period and overtime thresholds specified by the assignment.

**Rationale:** A single calculation implementation avoids inconsistent results across punch-in, punch-out, corrections, and analytics.

**Trade-off:** Boundary conditions require precise handling of seconds, minutes, and rounding. Tests should cover values immediately below, at, and above each threshold.

## 10. Work-Hour Precision

**Decision:** Use explicit decimal rounding when the contract requires half-up rounding.

**Rationale:** Python's default rounding behaviour may differ from the expected business rule at midpoint values.

**Trade-off:** Decimal calculations require explicit conversion and quantization rather than relying on binary floating-point rounding.

## 11. Manual Corrections and Auditability

**Decision:** Preserve an audit entry whenever an attendance record is manually corrected, following the contract's required history format.

**Rationale:** An audit trail makes changes traceable and prevents corrections from silently erasing the prior state.

**Trade-off:** Corrections must update the attendance record and its history consistently. Conditional updates should detect concurrent modifications instead of silently overwriting them.

## 12. Pagination and Filtering

**Decision:** Use one-based page numbering, bounded page sizes, and MongoDB-side filtering and pagination.

**Rationale:** This follows the API contract and avoids loading unnecessary records into application memory.

**Trade-off:** Correct counts must use the same filters as the result query, and stable sorting is needed for predictable pagination.

## 13. MongoDB Aggregation Pipelines

**Decision:** Implement the required analytics using MongoDB aggregation pipelines.

**Rationale:** Grouping and summarization in the database reduce unnecessary data transfer and meet the assignment's requirement to demonstrate MongoDB query capabilities.

**Trade-off:** Pipelines require careful validation against the expected output, particularly for empty departments, date ranges, duplicate records, and leaderboard ties.

## 14. Analytics and Derived Values

**Decision:** Follow the contract on whether analytics use stored derived attendance values or compute values inside an aggregation pipeline.

**Rationale:** This keeps reports consistent with the source records and the expected API behaviour.

**Trade-off:** Derived values must be maintained correctly when attendance records are created or corrected.

## 15. Indexing Strategy

**Decision:** Create required unique and query-supporting indexes idempotently during application startup.

**Rationale:** Unique indexes protect data integrity, while query-supporting indexes improve common lookups and filtering.

**Trade-off:** Indexes consume storage and add write overhead. Index definitions should reflect actual query patterns, and startup must handle index-creation failures safely.

## 16. Error Handling

**Decision:** Return consistent HTTP status codes and error bodies in accordance with the OpenAPI contract.

**Rationale:** Clients need to distinguish validation errors, missing resources, conflicts, and service failures.

**Trade-off:** Database exceptions must be translated into appropriate API responses without exposing internal details or secrets.

## 17. Health Checks and Query Explain

**Decision:** Make health reporting reflect database availability where required and restrict query-plan inspection to supported endpoint identifiers.

**Rationale:** A process that is running but cannot reach MongoDB may not be able to serve requests correctly. Explain functionality should not permit arbitrary database operations.

**Trade-off:** Database health checks need sensible timeouts, and query-plan output should avoid exposing sensitive information.

## 18. Testing Strategy

**Decision:** Combine automated unit tests with API and MongoDB integration tests.

**Rationale:** Unit tests can validate calculations and request validation, while integration tests are needed to verify persistence, indexes, concurrency behaviour, and aggregation results.

**Trade-off:** Integration tests require a configured MongoDB instance or dedicated test database. A passing unit-test suite alone does not prove full contract compliance.

## 19. Scope and Maintainability

**Decision:** Prioritize correctness, contract compliance, data integrity, and clear documentation over unrelated features.

**Rationale:** The assignment evaluates the specified API and the ability to explain technical choices.

**Trade-off:** Some production features may remain out of scope. Any incomplete requirement or known limitation must be documented honestly in `README.md`.

## Verification Status

These decisions describe the intended design. Each decision must be checked against the actual implementation and the supplied `openapi.yaml`. Features should only be described as implemented and verified when corresponding code and test results support that claim.
