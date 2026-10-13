"""
Employee Attendance & Analytics API — HROne candidate assignment.

Run from repository root:
    uvicorn app.main:app --port 8000

Configuration:
    MONGO_URI (required in production; defaults to local MongoDB for development)
    MONGO_DB  (defaults to attendance_db)

All application code intentionally remains in this file to match the assignment contract.
"""
import os
import re
import calendar
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Literal, Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Path
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError, PyMongoError
from bson import ObjectId

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))
UTC = timezone.utc
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "attendance_db")
client = MongoClient(MONGO_URI, tz_aware=True, serverSelectionTimeoutMS=5000)
db = client[MONGO_DB]

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")

PRESENCE_STATUSES = {"PRESENT", "WFH", "ON_DUTY"}
ALL_STATUSES = PRESENCE_STATUSES | {"ABSENT", "LEAVE"}
DERIVED_FIELDS = {"work_hours", "late_minutes", "overtime_minutes", "half_day"}


# --------------------------------------------------------------------------- #
# Validation, dates, and serialization helpers
# --------------------------------------------------------------------------- #
def parse_date(value: str, field: str = "date") -> date:
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except (ValueError, TypeError):
        raise HTTPException(422, f"{field} must be YYYY-MM-DD")


def month_bounds(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month or ""):
        raise HTTPException(422, "month must be YYYY-MM")
    year, mon = map(int, month.split("-"))
    last_day = calendar.monthrange(year, mon)[1]
    return f"{month}-01", f"{month}-{last_day:02d}"


def dt_from_ms(ms: int) -> datetime:
    # Whole-second precision is required by R1.
    return datetime.fromtimestamp(ms / 1000, tz=UTC).replace(microsecond=0)


def to_utc_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def epoch_ms(value: Optional[datetime]) -> Optional[int]:
    if value is None:
        return None
    return int(to_utc_aware(value).timestamp() * 1000)


def round_half_up(value: float, places: int = 2) -> float:
    quantum = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def shift_start_for(punch_in: datetime, shift_start: str, shift_end: str) -> datetime:
    local_in = to_utc_aware(punch_in).astimezone(IST)
    sh, sm = map(int, shift_start.split(":"))
    eh, em = map(int, shift_end.split(":"))
    start_day = local_in.date()
    # For an overnight shift, an early-morning punch belongs to yesterday's shift.
    if (eh, em) <= (sh, sm) and (local_in.hour, local_in.minute) < (eh, em):
        start_day -= timedelta(days=1)
    return datetime.combine(start_day, time(sh, sm), tzinfo=IST)


def shift_end_for(punch_in: datetime, shift_start: str, shift_end: str) -> datetime:
    start = shift_start_for(punch_in, shift_start, shift_end)
    eh, em = map(int, shift_end.split(":"))
    end_day = start.date()
    sh, sm = map(int, shift_start.split(":"))
    if (eh, em) <= (sh, sm):
        end_day += timedelta(days=1)
    return datetime.combine(end_day, time(eh, em), tzinfo=IST)


def attendance_date_for(punch_in: datetime, shift_start: str, shift_end: str) -> str:
    """Return the IST date on which the shift started (R1, including overnight shifts)."""
    return shift_start_for(punch_in, shift_start, shift_end).date().isoformat()


def compute_late_minutes(punch_in: datetime, shift_start: str, shift_end: str) -> int:
    actual = to_utc_aware(punch_in).astimezone(IST).replace(microsecond=0)
    start = shift_start_for(actual, shift_start, shift_end)
    diff = int((actual - start).total_seconds() // 60)
    return diff if (actual - start).total_seconds() > 600 else 0


def compute_work_hours(punch_in: datetime, punch_out: datetime) -> float:
    seconds = (to_utc_aware(punch_out) - to_utc_aware(punch_in)).total_seconds()
    return round_half_up(seconds / 3600, 2)


def compute_overtime(punch_out: datetime, punch_in: datetime, shift_start: str, shift_end: str) -> int:
    end = shift_end_for(punch_in, shift_start, shift_end)
    minutes = int((to_utc_aware(punch_out) - end.astimezone(UTC)).total_seconds() // 60)
    return minutes if minutes >= 30 else 0


def working_days_between(start: date, end: date) -> int:
    """Used only for input-independent date math; analytics record calculations run in MongoDB."""
    if start > end:
        return 0
    weeks, remainder = divmod((end - start).days + 1, 7)
    count = weeks * 5
    for i in range(remainder):
        if (start + timedelta(days=weeks * 7 + i)).weekday() < 5:
            count += 1
    return count


def clean_employee(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    if isinstance(doc.get("created_at"), datetime):
        doc["created_at"] = epoch_ms(doc["created_at"])
    return doc


def clean_attendance(doc: dict) -> dict:
    doc = dict(doc)
    doc.pop("_id", None)
    doc.setdefault("history", [])
    doc.setdefault("half_day", False)
    for key in ("punch_in", "punch_out"):
        if isinstance(doc.get(key), datetime):
            doc[key] = epoch_ms(doc[key])
    history = []
    for entry in doc.get("history") or []:
        entry = dict(entry)
        if isinstance(entry.get("at"), datetime):
            entry["at"] = epoch_ms(entry["at"])
        changes = {}
        for key, change in (entry.get("changes") or {}).items():
            change = dict(change)
            if key in {"punch_in", "punch_out"}:
                for side in ("from", "to"):
                    if isinstance(change.get(side), datetime):
                        change[side] = epoch_ms(change[side])
            changes[key] = change
        entry["changes"] = changes
        history.append(entry)
    doc["history"] = history
    return doc


def create_indexes() -> None:
    # Idempotent. Unique indexes also provide concurrency guarantees.
    db.employees.create_index([("emp_code", ASCENDING)], unique=True, name="uq_employee_code")
    db.employees.create_index([("department", ASCENDING), ("joined_on", ASCENDING)], name="department_joined")
    db.employees.create_index([("joined_on", ASCENDING)], name="employee_joined")
    db.employees.create_index([("department", ASCENDING), ("emp_code", ASCENDING)], name="department_employee")
    db.attendance_logs.create_index(
        [("emp_code", ASCENDING), ("date", ASCENDING)], unique=True, name="uq_attendance_employee_date"
    )
    db.attendance_logs.create_index([("date", DESCENDING), ("emp_code", ASCENDING)], name="attendance_date_employee")
    db.attendance_logs.create_index([("date", ASCENDING), ("status", ASCENDING)], name="attendance_date_status")
    db.attendance_logs.create_index([("emp_code", ASCENDING), ("punch_in", DESCENDING)], name="attendance_employee_punchin")


@app.on_event("startup")
def startup() -> None:
    create_indexes()


class EmployeeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str = Field(pattern=r"^EMP\d{4,6}$")
    name: str = Field(min_length=1, max_length=100)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    department: str = Field(min_length=1, max_length=50)
    shift_start: str = Field(default="09:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_end: str = Field(default="18:30", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    joined_on: str

    @field_validator("joined_on")
    @classmethod
    def valid_joined_on(cls, value):
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError
        except ValueError:
            raise ValueError("joined_on must be YYYY-MM-DD")
        return value

    @model_validator(mode="after")
    def distinct_shift_times(self):
        if self.shift_start == self.shift_end:
            raise ValueError("shift_start must differ from shift_end")
        return self


class PunchInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str = Field(min_length=1)
    punched_at: Optional[int] = Field(default=None, strict=True, ge=100000000000, le=4102444800000)
    status: Literal["PRESENT", "WFH", "ON_DUTY"] = "PRESENT"


class PunchOutIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    emp_code: str = Field(min_length=1)
    punched_at: Optional[int] = Field(default=None, strict=True, ge=100000000000, le=4102444800000)


class RegularizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=5, max_length=200)
    regularized_by: str = Field(min_length=1, max_length=50)
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None
    punch_in: Optional[int] = Field(default=None, strict=True, ge=100000000000, le=4102444800000)
    punch_out: Optional[int] = Field(default=None, strict=True, ge=100000000000, le=4102444800000)


def presence_expr(status_field="$status", half_field="$half_day"):
    return {
        "$cond": [
            {"$in": [status_field, ["PRESENT", "WFH", "ON_DUTY"]]},
            {"$cond": [{"$eq": [half_field, True]}, 0.5, 1.0]},
            0.0,
        ]
    }


# --------------------------------------------------------------------------- #
# Health and employee endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health():
    try:
        client.admin.command("ping")
        return {"status": "ok"}
    except PyMongoError:
        raise HTTPException(503, "MongoDB unavailable")


@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()
    doc["created_at"] = datetime.now(UTC).replace(microsecond=0)
    try:
        db.employees.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "emp_code already exists")
    return clean_employee(doc)


@app.get("/employees")
def list_employees(
    department: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    query = {"department": department} if department else {}
    total = db.employees.count_documents(query)
    items = [clean_employee(d) for d in db.employees.find(query, {"_id": 0}).sort("emp_code", ASCENDING).skip((page - 1) * page_size).limit(page_size)]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


# --------------------------------------------------------------------------- #
# Attendance endpoints
# --------------------------------------------------------------------------- #
@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = dt_from_ms(body.punched_at) if body.punched_at is not None else datetime.now(UTC).replace(microsecond=0)
    attendance_date = attendance_date_for(ts, emp["shift_start"], emp["shift_end"])
    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(ts, emp["shift_start"], emp["shift_end"]),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }
    try:
        db.attendance_logs.insert_one(doc)
    except DuplicateKeyError:
        raise HTTPException(409, "already punched in for this date")
    return clean_attendance(doc)


@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    ts = dt_from_ms(body.punched_at) if body.punched_at is not None else datetime.now(UTC).replace(microsecond=0)
    current = db.attendance_logs.find_one(
        {"emp_code": body.emp_code, "punch_in": {"$lte": ts}},
        sort=[("punch_in", DESCENDING)],
    )
    if not current:
        raise HTTPException(404, "no punch-in found")
    if current.get("punch_out") is not None:
        raise HTTPException(409, "record is already punched out")
    punch_in_at = to_utc_aware(current["punch_in"])
    elapsed = (ts - punch_in_at).total_seconds()
    if elapsed <= 0 or elapsed > 24 * 3600:
        raise HTTPException(422, "punched_at must be after punch_in and no more than 24 hours later")
    work_hours = compute_work_hours(punch_in_at, ts)
    update = {
        "punch_out": ts,
        "work_hours": work_hours,
        "overtime_minutes": compute_overtime(ts, punch_in_at, emp["shift_start"], emp["shift_end"]),
        "half_day": work_hours < 4.50,
    }
    result = db.attendance_logs.update_one(
        {"_id": current["_id"], "punch_out": None},
        {"$set": update},
    )
    if result.modified_count != 1:
        raise HTTPException(409, "record is already punched out")
    refreshed = db.attendance_logs.find_one({"_id": current["_id"]})
    return clean_attendance(refreshed)


@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    if date_from:
        parse_date(date_from, "date_from")
    if date_to:
        parse_date(date_to, "date_to")
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "date_from must be on or before date_to")
    query: dict[str, Any] = {}
    if emp_code:
        query["emp_code"] = emp_code
    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from
        if date_to:
            query["date"]["$lte"] = date_to
    if status:
        query["status"] = status
    total = db.attendance_logs.count_documents(query)
    docs = db.attendance_logs.find(query).sort([("date", DESCENDING), ("emp_code", ASCENDING)]).skip((page - 1) * page_size).limit(page_size)
    return {"items": [clean_attendance(d) for d in docs], "total": total, "page": page, "page_size": page_size}


@app.patch("/attendance/{emp_code}/{date}")
def regularize(emp_code: str, date: str, body: RegularizeIn):
    parse_date(date)
    emp = db.employees.find_one({"emp_code": emp_code})
    if not emp:
        raise HTTPException(404, "employee not found")
    key = {"emp_code": emp_code, "date": date}
    original = db.attendance_logs.find_one(key)
    if not original:
        raise HTTPException(404, "attendance record not found")

    proposed_status = body.status if body.status is not None else original["status"]
    if proposed_status in {"ABSENT", "LEAVE"} and (body.punch_in is not None or body.punch_out is not None):
        raise HTTPException(422, "ABSENT and LEAVE records cannot have punch times")
    if proposed_status in PRESENCE_STATUSES:
        raw_in = body.punch_in if body.punch_in is not None else epoch_ms(original.get("punch_in"))
        if raw_in is None:
            raise HTTPException(422, "presence status requires punch_in")

    final_in = dt_from_ms(body.punch_in) if body.punch_in is not None else original.get("punch_in")
    final_out = dt_from_ms(body.punch_out) if body.punch_out is not None else original.get("punch_out")
    if proposed_status in {"ABSENT", "LEAVE"}:
        final_in = final_out = None
    if proposed_status in PRESENCE_STATUSES and final_in is None:
        raise HTTPException(422, "presence status requires punch_in")
    if final_in is not None:
        expected_attendance_date = attendance_date_for(final_in, emp["shift_start"], emp["shift_end"])
        if expected_attendance_date != date:
            raise HTTPException(422, "punch_in must belong to the record's attendance date")
    if final_out is not None:
        if final_in is None:
            raise HTTPException(422, "punch_out requires punch_in")
        elapsed = (to_utc_aware(final_out) - to_utc_aware(final_in)).total_seconds()
        if elapsed <= 0 or elapsed > 24 * 3600:
            raise HTTPException(422, "punch_out must be after punch_in and within 24 hours")

    final = {
        "status": proposed_status,
        "punch_in": final_in,
        "punch_out": final_out,
        "work_hours": compute_work_hours(final_in, final_out) if final_in and final_out else None,
        "late_minutes": compute_late_minutes(final_in, emp["shift_start"], emp["shift_end"]) if final_in else 0,
        "overtime_minutes": compute_overtime(final_out, final_in, emp["shift_start"], emp["shift_end"]) if final_in and final_out else 0,
        "half_day": bool(final_in and final_out and compute_work_hours(final_in, final_out) < 4.50),
    }
    changed = {}
    for field, new_value in final.items():
        old_value = original.get(field, False if field == "half_day" else None)
        if field in {"punch_in", "punch_out"}:
            old_cmp = epoch_ms(old_value) if isinstance(old_value, datetime) else old_value
            new_cmp = epoch_ms(new_value) if isinstance(new_value, datetime) else new_value
        else:
            old_cmp, new_cmp = old_value, new_value
        if old_cmp != new_cmp:
            if field in {"punch_in", "punch_out"}:
                changed[field] = {"from": old_cmp, "to": new_cmp}
            else:
                changed[field] = {"from": old_cmp, "to": new_cmp}
    if not changed:
        raise HTTPException(422, "request does not change the record")
    history_entry = {
        "at": datetime.now(UTC).replace(microsecond=0),
        "by": body.regularized_by,
        "reason": body.reason,
        "changes": changed,
    }
    # Compare-and-swap on the current history and mutable fields prevents lost updates.
    compare = {"_id": original["_id"]}
    for f in ("status", "punch_in", "punch_out", "work_hours", "late_minutes", "overtime_minutes", "half_day"):
        if f in original:
            compare[f] = original[f]
        else:
            compare[f] = {"$exists": False}
    update = {"$set": final, "$push": {"history": history_entry}}
    try:
        result = db.attendance_logs.update_one(compare, update)
    except PyMongoError:
        raise HTTPException(409, "record changed concurrently; retry regularization")
    if result.modified_count != 1:
        raise HTTPException(409, "record changed concurrently; retry regularization")
    return clean_attendance(db.attendance_logs.find_one({"_id": original["_id"]}))


# --------------------------------------------------------------------------- #
# MongoDB aggregation pipeline builders
# --------------------------------------------------------------------------- #
def monthly_logs_lookup(month_start: str, month_end: str):
    return [
        {"$lookup": {
            "from": "attendance_logs",
            "let": {"code": "$emp_code", "joined": "$joined_on"},
            "pipeline": [
                {"$match": {"$expr": {"$and": [
                    {"$eq": ["$emp_code", "$$code"]},
                    {"$gte": ["$date", month_start]},
                    {"$gte": ["$date", "$$joined"]},
                    {"$lte": ["$date", month_end]},
                ]}}},
                {"$project": {"_id": 0, "date": 1, "status": 1, "half_day": 1, "work_hours": 1, "late_minutes": 1, "overtime_minutes": 1}},
            ],
            "as": "month_logs",
        }}
    ]


def employee_monthly_pipeline(emp_code: str, month: str):
    start, end = month_bounds(month)
    start_dt = datetime.combine(date.fromisoformat(start), time.min, tzinfo=UTC)
    end_dt = datetime.combine(date.fromisoformat(end), time.min, tzinfo=UTC)
    return [
        {"$match": {"emp_code": emp_code}},
        *monthly_logs_lookup(start, end),
        {"$set": {
            "effective_start": {"$max": ["$joined_on", start]},
            "month_start": start,
            "month_end": end,
        }},
        {"$set": {
            "working_days": {"$cond": [
                {"$gt": ["$effective_start", "$month_end"]}, 0,
                {"$size": {"$filter": {
                    "input": {"$map": {
                        "input": {"$range": [0, {"$add": [
                            {"$dateDiff": {
                                "startDate": {"$dateFromString": {"dateString": "$effective_start"}},
                                "endDate": {"$dateFromString": {"dateString": "$month_end"}},
                                "unit": "day"
                            }}, 1
                        ]}]},
                        "as": "n",
                        "in": {"$dateAdd": {
                            "startDate": {"$dateFromString": {"dateString": "$effective_start"}},
                            "unit": "day", "amount": "$$n"
                        }}
                    }},
                    "as": "d",
                    "cond": {"$and": [
                        {"$gte": [{"$dayOfWeek": "$$d"}, 2]},
                        {"$lte": [{"$dayOfWeek": "$$d"}, 6]}
                    ]}
                }}}
            ]},
            "present_days": {"$sum": {"$map": {
                "input": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$and": [
                    {"$in": ["$$l.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$gte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$$l.date"}}}, 2]},
                    {"$lte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$$l.date"}}}, 6]},
                ]}}},
                "as": "l", "in": {"$cond": [{"$eq": [{"$ifNull": ["$$l.half_day", False]}, True]}, 0.5, 1.0]}
            }}},
            "leave_days": {"$size": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$eq": ["$$l.status", "LEAVE"]}}}},
            "late_count": {"$size": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$gt": [{"$ifNull": ["$$l.late_minutes", 0]}, 0]}}}},
            "total_late_minutes": {"$sum": {"$map": {"input": "$month_logs", "as": "l", "in": {"$ifNull": ["$$l.late_minutes", 0]}}}},
            "total_overtime_minutes": {"$sum": {"$map": {"input": "$month_logs", "as": "l", "in": {"$ifNull": ["$$l.overtime_minutes", 0]}}}},
        }},
        {"$project": {
            "_id": 0, "emp_code": 1, "month": {"$literal": month},
            "working_days": 1, "present_days": {"$divide": [{"$floor": {"$add": [{"$multiply": ["$present_days", 100]}, 0.5]}}, 100]},
            "leave_days": 1, "late_count": 1, "total_late_minutes": 1, "total_overtime_minutes": 1,
            "attendance_pct": {"$cond": [
                {"$gt": ["$working_days", 0]},
                {"$divide": [{"$floor": {"$add": [{"$multiply": [{"$divide": ["$present_days", "$working_days"]}, 1000000]}, 0.5]}}, 10000]},
                None
            ]},
        }},
    ]


def department_summary_pipeline(month: str, department: Optional[str] = None):
    start, end = month_bounds(month)
    match = {"joined_on": {"$lte": end}}
    if department:
        match["department"] = department
    return [
        {"$match": match},
        *monthly_logs_lookup(start, end),
        {"$set": {
            "present_days_employee": {"$sum": {"$map": {
                "input": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$and": [
                    {"$in": ["$$l.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$gte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$$l.date"}}}, 2]},
                    {"$lte": [{"$dayOfWeek": {"$dateFromString": {"dateString": "$$l.date"}}}, 6]},
                ]}}},
                "as": "l", "in": {"$cond": [{"$eq": [{"$ifNull": ["$$l.half_day", False]}, True]}, 0.5, 1.0]}
            }}},
            "late_count_employee": {"$size": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$gt": [{"$ifNull": ["$$l.late_minutes", 0]}, 0]}}}},
            "late_minutes_employee": {"$sum": {"$map": {"input": "$month_logs", "as": "l", "in": {"$ifNull": ["$$l.late_minutes", 0]}}}},
            "leave_count_employee": {"$size": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$eq": ["$$l.status", "LEAVE"]}}}},
            "on_duty_employee": {"$size": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$eq": ["$$l.status", "ON_DUTY"]}}}},
            "present_work_hours": {"$map": {
                "input": {"$filter": {"input": "$month_logs", "as": "l", "cond": {"$and": [
                    {"$in": ["$$l.status", ["PRESENT", "WFH", "ON_DUTY"]]},
                    {"$ne": ["$$l.work_hours", None]}
                ]}}},
                "as": "l", "in": "$$l.work_hours"
            }},
        }},
        {"$set": {
            "present_work_hours_sum": {"$sum": "$present_work_hours"},
            "present_work_hours_count": {"$size": "$present_work_hours"}
        }},
        {"$group": {
            "_id": "$department",
            "headcount": {"$sum": 1},
            "present_days": {"$sum": "$present_days_employee"},
            "late_count": {"$sum": "$late_count_employee"},
            "total_late_minutes": {"$sum": "$late_minutes_employee"},
            "leave_count": {"$sum": "$leave_count_employee"},
            "on_duty_count": {"$sum": "$on_duty_employee"},
            "work_hours_sum": {"$sum": "$present_work_hours_sum"},
            "work_hours_count": {"$sum": "$present_work_hours_count"},
        }},
        {"$match": {"headcount": {"$gt": 0}}},
        {"$project": {
            "_id": 0, "department": "$_id", "headcount": 1,
            "present_days": {"$divide": [{"$floor": {"$add": [{"$multiply": ["$present_days", 100]}, 0.5]}}, 100]},
            "avg_work_hours": {"$cond": [
                {"$gt": ["$work_hours_count", 0]},
                {"$divide": [{"$floor": {"$add": [{"$multiply": [{"$divide": ["$work_hours_sum", "$work_hours_count"]}, 100]}, 0.5]}}, 100]},
                None
            ]},
            "late_count": 1, "total_late_minutes": 1, "leave_count": 1, "on_duty_count": 1,
        }},
        {"$sort": {"department": 1}},
    ]


def leaderboard_pipeline(month: str, limit: int, department: Optional[str] = None):
    start, end = month_bounds(month)
    pipeline = [
        {"$match": {"date": {"$gte": start, "$lte": end}, "late_minutes": {"$gt": 0}}},
        {"$group": {"_id": "$emp_code", "total_late_minutes": {"$sum": "$late_minutes"}, "late_count": {"$sum": 1}}},
        {"$match": {"total_late_minutes": {"$gt": 0}}},
        {"$lookup": {"from": "employees", "localField": "_id", "foreignField": "emp_code", "as": "employee"}},
        {"$unwind": "$employee"},
    ]
    if department:
        pipeline.append({"$match": {"employee.department": department}})
    pipeline.extend([
        {"$setWindowFields": {
            "sortBy": {"total_late_minutes": -1},
            "output": {"rank": {"$rank": {}}}
        }},
        {"$match": {"rank": {"$lte": limit}}},
        {"$sort": {"total_late_minutes": -1, "_id": 1}},
        {"$project": {
            "_id": 0, "rank": 1, "emp_code": "$_id", "name": "$employee.name",
            "department": "$employee.department", "total_late_minutes": 1, "late_count": 1,
        }},
    ])
    return pipeline


def trend_pipeline(department: str, start: date, end: date):
    lower = datetime.combine(start, time.min, tzinfo=UTC)
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=UTC)
    return [
        {"$documents": [{"day": lower}]},
        {"$densify": {"field": "day", "range": {"step": 1, "unit": "day", "bounds": [lower, upper]}}},
        {"$set": {"date": {"$dateToString": {"date": "$day", "format": "%Y-%m-%d", "timezone": "UTC"}}}},
        {"$lookup": {
            "from": "employees",
            "let": {"daystr": "$date"},
            "pipeline": [{"$match": {"$expr": {"$and": [
                {"$eq": ["$department", department]},
                {"$lte": ["$joined_on", "$$daystr"]},
            ]}}}, {"$count": "n"}],
            "as": "hc",
        }},
        {"$set": {"headcount": {"$ifNull": [{"$arrayElemAt": ["$hc.n", 0]}, 0]}}},
        {"$lookup": {
            "from": "attendance_logs",
            "localField": "date", "foreignField": "date",
            "pipeline": [
                {"$lookup": {"from": "employees", "localField": "emp_code", "foreignField": "emp_code", "as": "emp"}},
                {"$unwind": "$emp"},
                {"$match": {"$expr": {"$eq": ["$emp.department", department]}}},
                {"$group": {
                    "_id": None,
                    "present_count": {"$sum": {"$cond": [
                        {"$in": ["$status", ["PRESENT", "WFH", "ON_DUTY"]]},
                        {"$cond": [{"$eq": [{"$ifNull": ["$half_day", False]}, True]}, 0.5, 1.0]},
                        0
                    ]}},
                    "late_count": {"$sum": {"$cond": [{"$gt": [{"$ifNull": ["$late_minutes", 0]}, 0]}, 1, 0]}},
                }},
            ],
            "as": "daily",
        }},
        {"$set": {
            "present_count": {"$ifNull": [{"$arrayElemAt": ["$daily.present_count", 0]}, 0]},
            "late_count": {"$ifNull": [{"$arrayElemAt": ["$daily.late_count", 0]}, 0]},
            "is_working_day": {"$and": [{"$gte": [{"$dayOfWeek": "$day"}, 2]}, {"$lte": [{"$dayOfWeek": "$day"}, 6]}]},
        }},
        {"$set": {
            "attendance_rate": {"$cond": [
                {"$and": ["$is_working_day", {"$gt": ["$headcount", 0]}]},
                {"$divide": [{"$floor": {"$add": [{"$multiply": [{"$divide": ["$present_count", "$headcount"]}, 10000]}, 0.5]}}, 10000]},
                None
            ]}
        }},
        {"$setWindowFields": {
            "sortBy": {"day": 1},
            "output": {"moving_avg_7d": {"$avg": "$attendance_rate", "window": {"documents": [-6, 0]}}}
        }},
        {"$project": {
            "_id": 0, "date": 1, "is_working_day": 1, "headcount": 1,
            "present_count": {"$divide": [{"$floor": {"$add": [{"$multiply": ["$present_count", 100]}, 0.5]}}, 100]},
            "late_count": 1, "attendance_rate": {"$cond": [{"$ne": ["$attendance_rate", None]}, {"$divide": [{"$floor": {"$add": [{"$multiply": ["$attendance_rate", 10000]}, 0.5]}}, 10000]}, None]},
            "moving_avg_7d": {"$cond": [{"$ne": ["$moving_avg_7d", None]}, {"$divide": [{"$floor": {"$add": [{"$multiply": ["$moving_avg_7d", 10000]}, 0.5]}}, 10000]}, None]},
        }},
        {"$sort": {"date": 1}},
    ]


# --------------------------------------------------------------------------- #
# Analytics endpoints — calculations are performed in MongoDB pipelines
# --------------------------------------------------------------------------- #
@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")):
    month_bounds(month)
    if not db.employees.find_one({"emp_code": emp_code}, {"_id": 1}):
        raise HTTPException(404, "employee not found")
    rows = list(db.employees.aggregate(employee_monthly_pipeline(emp_code, month), allowDiskUse=True))
    if not rows:
        raise HTTPException(404, "employee not found")
    return rows[0]


@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
):
    month_bounds(month)
    rows = list(db.employees.aggregate(department_summary_pipeline(month, department), allowDiskUse=True))
    return {"month": month, "items": rows}


@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    month_bounds(month)
    rows = list(db.attendance_logs.aggregate(leaderboard_pipeline(month, limit, department), allowDiskUse=True))
    return {"month": month, "items": rows}


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    start = parse_date(from_date, "from")
    end = parse_date(to_date, "to")
    if end < start:
        raise HTTPException(422, "to must be on or after from")
    if (end - start).days + 1 > 92:
        raise HTTPException(422, "date range cannot exceed 92 days")
    if not db.employees.find_one({"department": department}, {"_id": 1}):
        raise HTTPException(404, "department not found")
    rows = list(db.aggregate(trend_pipeline(department, start, end), allowDiskUse=True))
    return {"department": department, "items": rows}


# --------------------------------------------------------------------------- #
# Explain endpoint. The command returns MongoDB's raw executionStats explain.
# --------------------------------------------------------------------------- #
@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: Literal["attendance_list", "employee_monthly", "department_summary", "late_leaderboard", "department_trend"],
    emp_code: Optional[str] = None,
    month: Optional[str] = Query(None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[Literal["PRESENT", "ABSENT", "LEAVE", "WFH", "ON_DUTY"]] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    if endpoint == "attendance_list":
        if date_from:
            parse_date(date_from, "date_from")
        if date_to:
            parse_date(date_to, "date_to")
        if date_from and date_to and date_from > date_to:
            raise HTTPException(422, "date_from must be on or before date_to")
        query: dict[str, Any] = {}
        if emp_code:
            query["emp_code"] = emp_code
        if date_from or date_to:
            query["date"] = {}
            if date_from: query["date"]["$gte"] = date_from
            if date_to: query["date"]["$lte"] = date_to
        if status: query["status"] = status
        coll, collection_name = db.attendance_logs, "attendance_logs"
        command = {"find": collection_name, "filter": query, "sort": {"date": -1, "emp_code": 1}, "skip": (page - 1) * page_size, "limit": page_size}
        explain = db.command("explain", command, verbosity="executionStats")
    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(422, "emp_code and month are required")
        month_bounds(month)
        pipeline = employee_monthly_pipeline(emp_code, month)
        collection_name = "employees"
        explain = db.command("explain", {"aggregate": "employees", "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(422, "month is required")
        month_bounds(month)
        pipeline = department_summary_pipeline(month, department)
        collection_name = "employees"
        explain = db.command("explain", {"aggregate": "employees", "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(422, "month is required")
        month_bounds(month)
        pipeline = leaderboard_pipeline(month, limit, department)
        collection_name = "attendance_logs"
        explain = db.command("explain", {"aggregate": "attendance_logs", "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
    else:
        if not department or not from_date or not to_date:
            raise HTTPException(422, "department, from and to are required")
        start = parse_date(from_date, "from")
        end = parse_date(to_date, "to")
        if end < start or (end - start).days + 1 > 92:
            raise HTTPException(422, "invalid trend date range")
        pipeline = trend_pipeline(department, start, end)
        # Database-level aggregation supports $documents as its first stage.
        explain = db.command("explain", {"aggregate": 1, "pipeline": pipeline, "cursor": {}, "allowDiskUse": True}, verbosity="executionStats")
        collection_name = "database"
    return {"endpoint": endpoint, "collection": collection_name, "explain": explain}
