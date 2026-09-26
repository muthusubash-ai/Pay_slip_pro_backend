def test_dashboard_stats(client, auth_headers):
    response = client.get("/api/v1/dashboard/stats", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_employees" in data
    assert "active_employees" in data
    assert "total_payroll" in data
    assert "avg_salary" in data


def test_payroll_summary(client, auth_headers):
    response = client.get("/api/v1/dashboard/payroll-summary?month=3&year=2026", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["month"] == 3
    assert data["year"] == 2026


def test_department_breakdown(client, auth_headers):
    response = client.get("/api/v1/dashboard/department-breakdown", headers=auth_headers)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
