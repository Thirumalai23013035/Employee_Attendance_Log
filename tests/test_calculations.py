"""Contract-focused unit tests that do not require a running MongoDB instance."""
from datetime import datetime, timezone, timedelta

from app.main import (
    IST,
    attendance_date_for,
    compute_late_minutes,
    compute_overtime,
    compute_work_hours,
    shift_end_for,
    working_days_between,
)


def dt_ist(day: int, hour: int, minute: int, second: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, second, tzinfo=IST)


def test_late_grace_period_is_strictly_more_than_ten_minutes():
    assert compute_late_minutes(dt_ist(6, 9, 40), "09:30", "18:30") == 0
    assert compute_late_minutes(dt_ist(6, 9, 40, 1), "09:30", "18:30") == 10
    assert compute_late_minutes(dt_ist(6, 10, 15, 59), "09:30", "18:30") == 45


def test_work_hours_round_half_up():
    start = dt_ist(6, 9, 0)
    end = start + timedelta(seconds=8 * 3600 + 7 * 60 + 30)
    assert compute_work_hours(start, end) == 8.13


def test_overtime_threshold_is_thirty_whole_minutes():
    punch_in = dt_ist(6, 9, 30)
    assert compute_overtime(dt_ist(6, 18, 59, 59), punch_in, "09:30", "18:30") == 0
    assert compute_overtime(dt_ist(6, 19, 0), punch_in, "09:30", "18:30") == 30


def test_overnight_attendance_date_is_shift_start_date():
    early_morning = dt_ist(7, 5, 55)
    assert attendance_date_for(early_morning, "22:00", "06:00") == "2026-07-06"
    assert shift_end_for(early_morning, "22:00", "06:00") == dt_ist(7, 6, 0)


def test_regular_shift_attendance_date_is_local_date():
    assert attendance_date_for(dt_ist(6, 9, 28), "09:30", "18:30") == "2026-07-06"


def test_working_days_count_weekdays_inclusive():
    from datetime import date
    assert working_days_between(date(2026, 7, 6), date(2026, 7, 10)) == 5
    assert working_days_between(date(2026, 7, 11), date(2026, 7, 12)) == 0
