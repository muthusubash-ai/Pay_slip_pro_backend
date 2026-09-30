from unittest.mock import Mock

import httpx

ADDRESS_URL = "/api/v1/locations/address-suggestions"
CITY_URL = "/api/v1/locations/city-suggestions"
PIN_URL = "/api/v1/locations/pin"


def test_location_lookup_requires_auth(client):
    assert client.get(ADDRESS_URL, {"q": "Anna Salai"}).status_code == 401
    assert client.get(CITY_URL, {"q": "Sank", "state": "Tamil Nadu"}).status_code == 401
    assert client.get(PIN_URL, {"code": "600001"}).status_code == 401


def test_location_lookup_rejects_invalid_input(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.location_lookup.httpx.get", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("External request")))
    assert client.get(ADDRESS_URL, {"q": "ab"}, headers=auth_headers).status_code == 400
    assert client.get(CITY_URL, {"q": "S", "state": "Tamil Nadu"}, headers=auth_headers).status_code == 400
    assert client.get(PIN_URL, {"code": "60001x"}, headers=auth_headers).status_code == 400


def test_address_suggestions_are_india_only_and_cached(client, auth_headers, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "features": [
            {"properties": {"name": "Anna Salai", "street": "Mount Road", "city": "Chennai", "state": "Tamil Nadu", "postcode": "600002", "countrycode": "IN"}},
            {"properties": {"name": "Outside India", "countrycode": "US"}},
        ]
    }
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("app.services.location_lookup.httpx.get", get)

    first = client.get(ADDRESS_URL, {"q": "Anna Salai"}, headers=auth_headers)
    second = client.get(ADDRESS_URL, {"q": "Anna Salai"}, headers=auth_headers)

    assert first.status_code == 200
    assert first.json()["items"] == [{
        "label": "Anna Salai, Mount Road, Chennai, Tamil Nadu, 600002",
        "address": "Anna Salai, Mount Road",
        "city": "Chennai",
        "state": "Tamil Nadu",
        "zip_code": "600002",
    }]
    assert second.status_code == 200
    get.assert_called_once()
    assert get.call_args.kwargs["params"]["countrycode"] == "IN"


def test_city_suggestions_filter_selected_state_and_cache(client, auth_headers, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "features": [
            {"properties": {"name": "Sankagiri", "state": "Tamil Nadu", "countrycode": "IN"}},
            {"properties": {"name": "Sankagiri", "state": "Tamil Nadu", "countrycode": "IN"}},
            {"properties": {"name": "Sankarpur", "state": "Bihar", "countrycode": "IN"}},
        ]
    }
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("app.services.location_lookup.httpx.get", get)

    first = client.get(CITY_URL, {"q": "Sank", "state": "Tamil Nadu"}, headers=auth_headers)
    second = client.get(CITY_URL, {"q": "Sank", "state": "Tamil Nadu"}, headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {"items": ["Sankagiri"]}
    assert second.status_code == 200
    get.assert_called_once()
    assert ("countrycode", "IN") in get.call_args.kwargs["params"]


def test_pin_lookup_returns_areas_and_caches(client, auth_headers, monkeypatch):
    response = Mock(status_code=200)
    response.json.return_value = {
        "places": [
            {"place name": "Chennai", "state": "Tamil Nadu"},
            {"place name": "Chennai", "state": "Tamil Nadu"},
            {"place name": "George Town", "state": "Tamil Nadu"},
        ]
    }
    response.raise_for_status.return_value = None
    get = Mock(return_value=response)
    monkeypatch.setattr("app.services.location_lookup.httpx.get", get)

    first = client.get(PIN_URL, {"code": "600001"}, headers=auth_headers)
    second = client.get(PIN_URL, {"code": "600001"}, headers=auth_headers)

    assert first.status_code == 200
    assert first.json() == {"pin_code": "600001", "places": [
        {"area": "Chennai", "state": "Tamil Nadu"},
        {"area": "George Town", "state": "Tamil Nadu"},
    ]}
    assert second.status_code == 200
    get.assert_called_once_with("https://api.zippopotam.us/IN/600001", timeout=5.0)


def test_pin_lookup_handles_missing_and_provider_failure(client, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.location_lookup.httpx.get", Mock(return_value=Mock(status_code=404)))
    assert client.get(PIN_URL, {"code": "999999"}, headers=auth_headers).status_code == 404

    def timeout(*args, **kwargs):
        raise httpx.TimeoutException("timeout")

    monkeypatch.setattr("app.services.location_lookup.httpx.get", timeout)
    assert client.get(PIN_URL, {"code": "600001"}, headers=auth_headers).status_code == 503
