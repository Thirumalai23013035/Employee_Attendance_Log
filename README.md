# Employee Attendance & Analytics API

FastAPI + MongoDB implementation for the HROne Software Engineer Trainee assignment.

## Setup

Requires Python 3.11+ and MongoDB 6.0+ (Atlas M0 is fine).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set `MONGO_URI` and `MONGO_DB`. Never commit `.env` or credentials.
The application uses the exact environment variable names `MONGO_URI` and `MONGO_DB`.

```powershell
python -m uvicorn app.main:app --port 8000
```

Optional sample data: `sample_seed.py` **deletes and replaces** both `employees` and
`attendance_logs`. Do not run it against a database containing data you need. To seed a
separate disposable database, set `MONGO_DB=hrone_attendance_test` and
`SEED_SAMPLE_DATA=true` in the shell environment, then run `python sample_seed.py`.
The script refuses to run unless the opt-in flag is set.

Open `http://127.0.0.1:8000/docs` for interactive API docs and `http://127.0.0.1:8000/health` to verify readiness.

## Implementation notes

- All application routes and pipeline builders are in `app/main.py`, as required by the candidate kit.
- Indexes are created idempotently at startup.
- Analytics calculations use MongoDB aggregation pipelines.
- `sample_seed.py` replaces the two collections' contents with the supplied sample data; use it only against a development database.
- The API uses `MONGO_URI` and `MONGO_DB`; environment variables override `.env` values.

## Tests

Install dependencies, then run:

```powershell
python -m pytest -q
```

The included tests cover calculation boundaries and the required route surface without requiring a live database. Run integration tests against a disposable MongoDB database before submission.

## Before submission

Test every endpoint against `openapi.yaml`, especially simultaneous punch-in/punch-out/regularization requests, overnight shifts, joiners, ties in the leaderboard, and trend ranges with no attendance logs. The supplied sample dataset is not sufficient to prove correctness on the hidden dataset. The grading environment may use MongoDB 6.0+, so validate aggregation operators on a matching MongoDB version.
