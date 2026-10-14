# Employee Attendance & Analytics API

A REST API for employee management, attendance tracking, manual attendance corrections, and analytics, built using **Python, FastAPI, and MongoDB**.

## Features

- Employee creation and listing with pagination and filtering.
- Attendance punch-in and punch-out.
- Late-arrival, work-hours, and overtime calculations.
- Manual attendance corrections with audit history.
- Monthly employee attendance analytics.
- Department attendance summaries and trends.
- Late-arrival leaderboard.
- MongoDB indexes and query-plan inspection.
- API documentation through Swagger UI.

## Technology Stack

- Python 3.11+
- FastAPI
- MongoDB 6.0+
- PyMongo
- Pydantic
- Pytest

## Project Structure

```text
hrone-attendance-api/
├── app/
│   ├── __init__.py
│   └── main.py
├── tests/
├── sample_data/
├── openapi.yaml
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
├── DATA_MODEL.md
└── .env.example
```

## Prerequisites

- Python 3.11 or newer
- MongoDB 6.0 or newer, locally or through MongoDB Atlas
- Git

## Setup

Clone the repository:

```bash
git clone https://github.com/Thirumalai23013035/Employee_Attendance_Log.git
cd Employee_Attendance_Log
```

Create and activate a virtual environment.

**Windows PowerShell:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create a local `.env` file based on `.env.example` and configure your MongoDB connection:

```env
MONGO_URI="your_mongodb_connection_string"
MONGO_DB="hrone_attendance"
```

Never commit `.env` or expose database credentials.

## Run the Application

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- API: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

## API Endpoint Overview

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/employees` | Create an employee |
| GET | `/employees` | List employees |
| POST | `/attendance/punch-in` | Record punch-in |
| POST | `/attendance/punch-out` | Record punch-out |
| GET | `/attendance` | Retrieve attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Correct attendance |
| GET | `/analytics/employees/{emp_code}/monthly` | Monthly employee analytics |
| GET | `/analytics/departments/summary` | Department summary |
| GET | `/analytics/leaderboard/late` | Late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Department attendance trend |
| GET | `/admin/explain/{endpoint}` | Inspect supported query plans |

Refer to `openapi.yaml` and Swagger UI for exact request fields, parameters, response schemas, and status codes.

## Run Tests

```bash
python -m pytest -q
```

Passing the included tests does not by itself guarantee full compliance. Verify the API contract, business rules, aggregation results, and MongoDB integration before submission.

## Database Notes

The application uses MongoDB for employee records and attendance logs. Database and collection names are configured through environment variables. Indexes should be created idempotently.

Use a separate test database when loading sample data. Inspect the seed script before running it, especially if it deletes or replaces existing records.

## Documentation

- `openapi.yaml` — API contract.
- `DATA_MODEL.md` — Database design.
- `REVIEW.md` — Review of the starter implementation.
- `DECISIONS.md` — Design decisions and trade-offs.

## Security

- Keep credentials in a local `.env` file.
- Never commit secrets or real connection strings.
- Do not expose personal employee information in public sample data.
- Use a dedicated test database for testing.

## Assignment

This project was developed for the HROne Software Engineer Trainee technical assignment.
