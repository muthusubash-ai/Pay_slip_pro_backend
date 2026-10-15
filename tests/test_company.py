def test_get_company_empty(client, auth_headers):
    response = client.get("/api/v1/company/", headers=auth_headers)
    assert response.status_code == 200


def test_update_company(client, auth_headers):
    response = client.put("/api/v1/company/", json={
        "company_name": "Acme Corp",
        "city": "Mumbai",
        "pay_day": 1,
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["company_name"] == "Acme Corp"
    assert data["city"] == "Mumbai"
    assert data["pay_day"] == 1


def test_update_company_twice(client, auth_headers):
    client.put("/api/v1/company/", json={"company_name": "Acme Corp"}, headers=auth_headers)
    response = client.put("/api/v1/company/", json={"company_name": "Acme Corp v2"}, headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["company_name"] == "Acme Corp v2"


def test_enable_employee_shift_timing_defaults_off(client, auth_headers):
    client.put("/api/v1/company/", json={"company_name": "Acme Corp"}, headers=auth_headers)
    response = client.get("/api/v1/company/", headers=auth_headers)
    assert response.json()["enable_employee_shift_timing"] is False


def test_toggle_enable_employee_shift_timing(client, auth_headers):
    response = client.put(
        "/api/v1/company/", json={"enable_employee_shift_timing": True}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["enable_employee_shift_timing"] is True

    response2 = client.put(
        "/api/v1/company/", json={"enable_employee_shift_timing": False}, headers=auth_headers
    )
    assert response2.status_code == 200
    assert response2.json()["enable_employee_shift_timing"] is False


def test_update_company_office_timing(client, auth_headers):
    response = client.put("/api/v1/company/", json={
        "company_name": "Acme Corp",
        "office_timing": "10:00 AM - 07:00 PM",
        "office_start_time": "10:00",
        "office_end_time": "19:00",
    }, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["office_timing"] == "10:00 AM - 07:00 PM"
    assert data["office_start_time"] == "10:00"
    assert data["office_end_time"] == "19:00"

