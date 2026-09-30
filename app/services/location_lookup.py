"""Public India address and PIN lookups for company settings."""

import hashlib
import re

import httpx
from django.core.cache import cache


def suggest_addresses(query: str) -> list[dict]:
    search = " ".join(query.strip().split())
    if len(search) < 4 or len(search) > 120:
        raise ValueError("Enter 4-120 characters to search for an address.")

    query_digest = hashlib.sha256(search.casefold().encode("utf-8")).hexdigest()
    cache_key = f"address-suggest:in:{query_digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = httpx.get(
        "https://photon.komoot.io/api/",
        params={"q": search, "countrycode": "IN", "limit": 5, "lang": "en"},
        headers={"User-Agent": "PaySlipPro/1.0 (company address autocomplete)"},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise TypeError("Address lookup returned invalid data.")

    suggestions = []
    seen = set()
    for feature in payload["features"][:10]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict) or str(props.get("countrycode", "")).upper() != "IN":
            continue
        name = str(props.get("name") or "").strip()
        street = " ".join(str(props.get(key) or "").strip() for key in ("housenumber", "street")).strip()
        address_parts = [name] if name else []
        if street and street.casefold() != name.casefold():
            address_parts.append(street)
        address = ", ".join(address_parts)
        city = str(props.get("city") or props.get("county") or "").strip()
        state = str(props.get("state") or "").strip()
        postcode = str(props.get("postcode") or "").strip()
        if not address:
            continue
        label = ", ".join(part for part in (address, city, state, postcode) if part)
        if label.casefold() in seen:
            continue
        seen.add(label.casefold())
        suggestions.append({"label": label, "address": address, "city": city, "state": state, "zip_code": postcode})
        if len(suggestions) == 5:
            break

    cache.set(cache_key, suggestions, timeout=12 * 60 * 60)
    return suggestions


def suggest_cities(query: str, state: str) -> list[str]:
    search = " ".join(query.strip().split())
    region = " ".join(state.strip().split())
    if not (2 <= len(search) <= 80 and 2 <= len(region) <= 100):
        raise ValueError("Enter a state and at least 2 city characters.")

    digest = hashlib.sha256(f"{region.casefold()}:{search.casefold()}".encode()).hexdigest()
    cache_key = f"city-suggest:in:{digest}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = httpx.get(
        "https://photon.komoot.io/api/",
        params=[
            ("q", f"{search}, {region}"), ("countrycode", "IN"), ("limit", 20),
            ("layer", "city"), ("layer", "locality"),
        ],
        headers={"User-Agent": "PaySlipPro/1.0 (company city autocomplete)"},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
        raise TypeError("City lookup returned invalid data.")

    cities = []
    seen = set()
    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        if str(props.get("countrycode") or "").upper() != "IN":
            continue
        if str(props.get("state") or "").casefold() != region.casefold():
            continue
        name = str(props.get("name") or "").strip()
        if name and name.casefold() not in seen:
            cities.append(name)
            seen.add(name.casefold())
        if len(cities) == 8:
            break

    cache.set(cache_key, cities, timeout=12 * 60 * 60)
    return cities


def lookup_indian_pin(code: str) -> dict | None:
    pin = code.strip()
    if not re.fullmatch(r"\d{6}", pin):
        raise ValueError("Enter a valid 6-digit Indian PIN code.")

    cache_key = f"pin:in:{pin}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = httpx.get(f"https://api.zippopotam.us/IN/{pin}", timeout=5.0)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or not isinstance(payload.get("places"), list):
        raise TypeError("PIN lookup returned invalid data.")

    places = []
    seen = set()
    for place in payload["places"]:
        if not isinstance(place, dict):
            continue
        area = str(place.get("place name") or "").strip()
        state = str(place.get("state") or "").strip()
        if not area or not state or (area.casefold(), state.casefold()) in seen:
            continue
        seen.add((area.casefold(), state.casefold()))
        places.append({"area": area, "state": state})
        if len(places) == 12:
            break

    result = {"pin_code": pin, "places": places}
    cache.set(cache_key, result, timeout=24 * 60 * 60)
    return result
