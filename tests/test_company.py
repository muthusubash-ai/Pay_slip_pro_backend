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
