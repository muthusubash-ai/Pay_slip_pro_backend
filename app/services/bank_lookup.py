"""Lookup public IFSC branch details without exposing arbitrary outbound URLs."""

import re

import httpx
from django.core.cache import cache

IFSC_PATTERN = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
IFSC_API_ROOT = "https://ifsc.razorpay.com"


def lookup_ifsc(code: str) -> dict | None:
    normalized = code.strip().upper()
    if not IFSC_PATTERN.fullmatch(normalized):
        raise ValueError("Enter a valid 11-character IFSC code.")

    cached = cache.get(f"ifsc:{normalized}")
    if cached is not None:
        return cached

    response = httpx.get(f"{IFSC_API_ROOT}/{normalized}", timeout=5.0)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    payload = response.json()
    if (
        not isinstance(payload, dict)
        or payload.get("IFSC") != normalized
        or not payload.get("BANK")
        or not payload.get("BRANCH")
    ):
        raise ValueError("IFSC lookup returned invalid branch details.")

    details = {
        "ifsc": normalized,
        "bank": str(payload.get("BANK") or "").strip(),
        "branch": str(payload.get("BRANCH") or "").strip(),
        "city": str(payload.get("CITY") or "").strip(),
        "state": str(payload.get("STATE") or "").strip(),
        "address": str(payload.get("ADDRESS") or "").strip(),
    }
    cache.set(f"ifsc:{normalized}", details, timeout=24 * 60 * 60)
    return details
