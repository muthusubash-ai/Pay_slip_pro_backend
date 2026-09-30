from unittest.mock import Mock

import httpx

URL = "/api/v1/banks/ifsc"


def test_ifsc_lookup_requires_auth(client):
    response = client.get(URL, {"code": "SBIN0000001"})
    assert response.status_code == 401


def test_ifsc_lookup_rejects_invalid_code_without_external_call(client, auth_headers, monkeypatch):
    def unexpected_call(*args, **kwargs):
        raise AssertionError("External API must not be called for invalid IFSC")

    monkeypatch.setattr("app.services.bank_lookup.httpx.get", unexpected_call)
    response = client.get(URL, {"code": "not-an-ifsc"}, headers=auth_headers)
    assert response.status_code == 400


def test_ifsc_lookup_returns_branch_and_caches_result(client, auth_headers, monkeypatch):
    external_response = Mock(status_code=200)
    external_response.json.return_value = {
        "IFSC": "SBIN0000001",
        "BANK": "State Bank of India",
        "BRANCH": "KOLKATA MAIN",
        "CITY": "KOLKATA",
        "STATE": "WEST BENGAL",
        "ADDRESS": "1 MAIN ROAD",
    }
    external_response.raise_for_status.return_value = None
    http_get = Mock(return_value=external_response)
    monkeypatch.setattr("app.services.bank_lookup.httpx.get", http_get)

    first = client.get(URL, {"code": "sbin0000001"}, headers=auth_headers)
    second = client.get(URL, {"code": "SBIN0000001"}, headers=auth_headers)

    assert first.status_code == 200
    assert first.json()["branch"] == "KOLKATA MAIN"
    assert first.json()["bank"] == "State Bank of India"
    assert second.status_code == 200
    http_get.assert_called_once_with("https://ifsc.razorpay.com/SBIN0000001", timeout=5.0)


def test_ifsc_lookup_reports_missing_branch(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.bank_lookup.httpx.get", Mock(return_value=Mock(status_code=404)))
    response = client.get(URL, {"code": "SBIN0000002"}, headers=auth_headers)
    assert response.status_code == 404


def test_ifsc_lookup_handles_provider_failure(client, auth_headers, monkeypatch):
    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.bank_lookup.httpx.get", timeout)
    response = client.get(URL, {"code": "SBIN0000003"}, headers=auth_headers)
    assert response.status_code == 503
