"""Smoke checks for the route surface required by openapi.yaml."""
from app.main import app


def test_required_paths_are_registered():
    paths = app.openapi()["paths"]
    expected = {
        "/health", "/employees", "/attendance/punch-in", "/attendance/punch-out",
        "/attendance", "/attendance/{emp_code}/{date}",
        "/analytics/employees/{emp_code}/monthly", "/analytics/departments/summary",
        "/analytics/leaderboard/late", "/analytics/departments/{department}/trend",
        "/admin/explain/{endpoint}",
    }
    assert expected.issubset(paths.keys())
    assert "post" in paths["/employees"]
    assert "get" in paths["/employees"]
    assert "patch" in paths["/attendance/{emp_code}/{date}"]
