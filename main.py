# main.py
import asyncio
import json
import math
import os
import time
import uuid
from datetime import datetime, timedelta

from crewai import Crew
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from json_repair import repair_json

from agents.city_selection import city_selection_agent, create_city_selection_task
from agents.flight_expert import flight_expert_agent, create_flight_estimation_task
from agents.local_expert import local_expert_agent, create_local_expert_task
from agents.travel_concierge import travel_concierge_agent, create_travel_concierge_task

# Approximate FX rates relative to USD (1 USD = X units of currency).
# Used to convert costs between the destination's local currency and the
# user's budget currency. Rates are intentionally simple/static so the
# demo works fully offline; refresh periodically or wire to an FX API later.
#
# Coverage: all ISO 4217 codes the City Scout / Local Expert have produced
# in our test runs so far, plus most popular travel destinations. If a code
# is missing, `convert_currency` logs a warning and returns the original
# amount — which the user sees as a misleading 1:1 conversion. ALWAYS add
# new codes here when you see that warning in the logs.
USD_RATES = {
    # Major reserve currencies
    "USD": 1.0,
    "EUR": 0.93,
    "GBP": 0.79,
    "JPY": 155.0,
    "CHF": 0.87,
    # North America
    "CAD": 1.37,
    "MXN": 17.0,
    # Latin America
    "BRL": 5.0,
    "ARS": 1000.0,    # Argentine Peso (highly inflationary — refresh often)
    "CLP": 950.0,     # Chilean Peso
    "COP": 4300.0,    # Colombian Peso  ← was missing, the cause of the Medellín bug
    "PEN": 3.7,       # Peruvian Sol
    "UYU": 39.0,      # Uruguayan Peso
    "BOB": 6.9,       # Bolivian Boliviano
    "DOP": 58.0,      # Dominican Peso
    "CRC": 520.0,     # Costa Rican Colon
    "GTQ": 7.8,       # Guatemalan Quetzal
    "PYG": 7300.0,    # Paraguayan Guaraní
    # South Asia
    "INR": 88.0,
    "PKR": 278.0,     # Pakistani Rupee
    "BDT": 119.0,     # Bangladeshi Taka
    "LKR": 300.0,     # Sri Lankan Rupee
    "NPR": 134.0,     # Nepalese Rupee  ← was missing, caused Kathmandu 1:1
    "BTN": 84.0,      # Bhutanese Ngultrum
    "MVR": 15.4,      # Maldivian Rufiyaa
    # East / Southeast Asia
    "CNY": 7.2,
    "HKD": 7.83,
    "TWD": 32.5,
    "KRW": 1380.0,
    "MOP": 8.05,      # Macanese Pataca
    "MNT": 3450.0,    # Mongolian Tögrög
    "SGD": 1.34,
    "MYR": 4.7,
    "THB": 35.0,
    "VND": 25000.0,
    "IDR": 16000.0,
    "PHP": 56.0,
    "KHR": 4100.0,    # Cambodian Riel
    "LAK": 21500.0,   # Lao Kip
    "MMK": 2100.0,    # Myanmar Kyat
    "BND": 1.34,      # Brunei Dollar
    # Middle East
    "AED": 3.67,
    "SAR": 3.75,
    "QAR": 3.64,
    "KWD": 0.31,
    "BHD": 0.38,
    "OMR": 0.39,
    "ILS": 3.7,
    "JOD": 0.71,
    "LBP": 89500.0,   # Lebanese Pound
    "TRY": 32.0,
    # Africa
    "EGP": 49.0,
    "MAD": 10.0,      # Moroccan Dirham
    "TND": 3.1,       # Tunisian Dinar
    "ZAR": 18.5,
    "KES": 130.0,     # Kenyan Shilling
    "TZS": 2700.0,    # Tanzanian Shilling
    "UGX": 3700.0,    # Ugandan Shilling
    "GHS": 15.0,      # Ghanaian Cedi
    "NGN": 1600.0,    # Nigerian Naira
    "ETB": 120.0,     # Ethiopian Birr
    "MUR": 46.0,      # Mauritian Rupee
    "RWF": 1340.0,    # Rwandan Franc
    # Oceania
    "AUD": 1.52,
    "NZD": 1.65,
    "FJD": 2.27,
    # Europe (non-Eurozone)
    "SEK": 10.6,
    "NOK": 10.8,
    "DKK": 6.9,
    "ISK": 138.0,     # Icelandic Króna
    "PLN": 4.0,
    "CZK": 23.5,
    "HUF": 365.0,
    "RON": 4.6,       # Romanian Leu
    "BGN": 1.82,
    "RSD": 109.0,     # Serbian Dinar
    "HRK": 7.0,       # Croatian Kuna (legacy — Croatia uses EUR since 2023)
    "ALL": 95.0,      # Albanian Lek
    "MKD": 57.0,      # Macedonian Denar
    "BAM": 1.82,      # Bosnia & Herzegovina Mark
    "UAH": 41.0,      # Ukrainian Hryvnia
    "GEL": 2.7,       # Georgian Lari
    "AMD": 390.0,     # Armenian Dram
    "AZN": 1.7,       # Azerbaijani Manat
    "RUB": 95.0,
    "BYN": 3.27,      # Belarusian Ruble
    "MDL": 17.5,      # Moldovan Leu
}


def convert_currency(amount: float, from_cur: str, to_cur: str) -> float:
    """Convert an amount from one ISO 4217 currency to another via USD.
    Falls back to the original amount if either currency is unknown — this
    is a 1:1 conversion that is almost always wrong, so we also log a
    warning so missing currencies surface during development.
    """
    if not isinstance(amount, (int, float)):
        return 0.0
    from_cur = (from_cur or "USD").upper()
    to_cur = (to_cur or "USD").upper()
    if from_cur == to_cur:
        return float(amount)
    rate_from = USD_RATES.get(from_cur)
    rate_to = USD_RATES.get(to_cur)
    if rate_from is None or rate_to is None:
        missing = ", ".join(c for c, r in [(from_cur, rate_from), (to_cur, rate_to)] if r is None)
        print(f"[convert_currency] WARNING: missing FX rate(s) for {missing} — returning {amount} unchanged. Add to USD_RATES in main.py.")
        return float(amount)
    in_usd = float(amount) / rate_from
    return round(in_usd * rate_to, 2)


def parse_llm_json(text: str) -> dict:
    """Parse a possibly-malformed JSON string from an LLM response.
    Returns an empty dict for non-object payloads so callers can rely on
    `.get(...)` access.
    """
    repaired = repair_json(str(text), return_objects=True)
    if isinstance(repaired, dict):
        return repaired
    return {}


# ---------------------------------------------------------------------------
# Guardrail: Unavailable Activity Detection
# ---------------------------------------------------------------------------
# Maps activity keywords to geographic constraints. When a user asks for an
# activity during /refine, we check whether the destination satisfies the
# constraint using an LLM call. If not, we short-circuit the expensive
# agent pipeline and return a structured warning with an alternative.

ACTIVITY_CONSTRAINTS: dict[str, dict] = {
    "beach": {
        "requires": "coastal",
        "label": "beach",
        "reason_template": "'{destination}' is a landlocked city with no coastline",
    },
    "snorkeling": {
        "requires": "coastal",
        "label": "snorkeling",
        "reason_template": "'{destination}' is landlocked — there's no ocean or reef nearby",
    },
    "surfing": {
        "requires": "coastal",
        "label": "surfing",
        "reason_template": "'{destination}' is not on the coast, so surfing isn't possible",
    },
    "scuba": {
        "requires": "coastal",
        "label": "scuba diving",
        "reason_template": "'{destination}' is landlocked — no dive sites nearby",
    },
    "skiing": {
        "requires": "mountain_snow",
        "label": "skiing",
        "reason_template": "'{destination}' doesn't have ski resorts or snow-capped mountains nearby",
    },
    "snowboarding": {
        "requires": "mountain_snow",
        "label": "snowboarding",
        "reason_template": "'{destination}' doesn't have ski resorts or snow-capped mountains nearby",
    },
}


_feasibility_llm = None

def _get_feasibility_llm():
    """Lazy-init a shared lightweight LLM for guardrail checks."""
    global _feasibility_llm
    if _feasibility_llm is None:
        from crewai import LLM
        _feasibility_llm = LLM(
            model="mistral/mistral-small-latest",
            api_key=os.getenv("MISTRAL_API_KEY"),
            temperature=0.0,
        )
    return _feasibility_llm


async def check_activity_feasibility(refinement: str, destination: str) -> dict | None:
    """Check if a refinement request asks for a geographically impossible
    activity. Returns a warning dict if infeasible, None if OK.

    Uses static geography knowledge for known cities (instant) and falls
    back to a single LLM call that checks feasibility + suggests an
    alternative in one round-trip.
    """
    refinement_lower = refinement.lower()
    matched_constraints: list[dict] = []
    for keyword, constraint in ACTIVITY_CONSTRAINTS.items():
        if keyword in refinement_lower:
            matched_constraints.append({**constraint, "keyword": keyword})

    if not matched_constraints:
        return None

    dest_lower = destination.strip().lower()

    for constraint in matched_constraints:
        req = constraint["requires"]
        is_infeasible = False

        # Fast path: use static knowledge for known landlocked cities
        if req == "coastal" and dest_lower in KNOWN_LANDLOCKED_CITIES:
            is_infeasible = True
        elif req == "mountain_snow" and dest_lower in {
            "jaipur", "goa", "mumbai", "chennai", "hyderabad", "kolkata",
            "dubai", "singapore", "bangkok", "cairo", "nairobi",
            "miami", "cape town", "rio de janeiro", "hanoi",
        }:
            is_infeasible = True

        if is_infeasible:
            suggestion = CATEGORY_SUGGESTIONS.get(
                constraint["keyword"],
                f"We've included nearby alternatives in {destination} instead.",
            )
            return {
                "type": "unavailable_activity",
                "activity": constraint["label"],
                "destination": destination,
                "reason": constraint["reason_template"].format(destination=destination),
                "suggestion": suggestion,
            }

        # Slow path: unknown city — ask LLM to check feasibility only
        if req == "coastal":
            geo_question = f"Is {destination} a coastal city on the ocean or sea?"
        elif req == "mountain_snow":
            geo_question = f"Does {destination} have ski resorts or snow-capped mountains within 100km?"
        else:
            continue

        combined_prompt = (
            f"{geo_question}\n"
            f"Reply with ONLY 'YES' or 'NO'."
        )
        llm = _get_feasibility_llm()
        response = await asyncio.to_thread(
            llm.call, [{"role": "user", "content": combined_prompt}]
        )
        text = (response or "").strip().upper()

        if "NO" in text and "YES" not in text:
            suggestion = CATEGORY_SUGGESTIONS.get(
                constraint["keyword"],
                f"We've included nearby alternatives in {destination} instead.",
            )
            return {
                "type": "unavailable_activity",
                "activity": constraint["label"],
                "destination": destination,
                "reason": constraint["reason_template"].format(destination=destination),
                "suggestion": suggestion,
            }

    return None


# ---------------------------------------------------------------------------
# Guardrail: Category filter — catch semantically impossible places
# ---------------------------------------------------------------------------

LANDLOCKED_KEYWORDS = {"beach", "snorkeling", "snorkel", "scuba", "surf", "surfing", "diving", "reef", "ocean", "seaside", "coastal"}
FAKE_ACTIVITY_KEYWORDS = {
    "jet ski", "jet skiing", "parasailing", "paragliding", "windsurfing",
    "kitesurfing", "kite surfing", "waterskiing", "water skiing",
    "wakeboarding", "paddleboarding", "snorkeling", "scuba",
    "surfing", "deep sea", "white water rafting",
}
KNOWN_LANDLOCKED_CITIES: set[str] = {
    "hyderabad", "jaipur", "delhi", "new delhi", "lucknow", "agra", "varanasi",
    "nagpur", "bhopal", "indore", "ahmedabad", "pune", "bangalore", "bengaluru",
    "mysore", "mysuru", "chandigarh", "amritsar", "jodhpur", "udaipur",
    "paris", "berlin", "prague", "vienna", "madrid", "budapest", "zurich",
    "moscow", "beijing", "mexico city", "bogota", "kathmandu", "addis ababa",
    "nairobi", "johannesburg", "denver", "nashville", "austin", "las vegas",
    "cairo", "marrakech", "seoul", "taipei",
}


CATEGORY_SUGGESTIONS: dict[str, str] = {
    "beach": "Try visiting lakes, riverside promenades, or public pools for a similar relaxfing vibe.",
    "snorkeling": "Consider aquariums or boat rides on local lakes for a water-based experience.",
    "snorkel": "Consider aquariums or boat rides on local lakes for a water-based experience.",
    "scuba": "Try indoor diving centres, aquariums, or boat rides on nearby lakes instead.",
    "surf": "Look for water parks, wakeboarding, or kayaking on local lakes for a water-sport fix.",
    "surfing": "Look for water parks, wakeboarding, or kayaking on local lakes for a water-sport fix.",
    "diving": "Try indoor diving centres or explore local aquariums instead.",
    "reef": "Visit local aquariums or nature reserves for a similar nature experience.",
    "ocean": "Explore local lakes, rivers, or reservoir parks for waterfront scenery.",
    "seaside": "Try lakeside parks, river walks, or botanical gardens for relaxing outdoor time.",
    "coastal": "Explore local lakes, rivers, or reservoir parks for waterfront scenery.",
    "skiing": "Try indoor snow parks, ice skating rinks, or adventure sports like rock climbing instead.",
    "snowboarding": "Try indoor snow parks, ice skating rinks, or adventure sports like rock climbing instead.",
}


def _check_interests_feasibility(
    interests: list[str], destination: str
) -> list[dict]:
    """Check user-supplied interests against ACTIVITY_CONSTRAINTS for the
    destination. Returns a list of warning dicts for any impossible interests.
    This runs synchronously (no LLM call) using static knowledge."""
    if not interests or not destination:
        return []
    dest_lower = destination.strip().lower()
    if dest_lower not in KNOWN_LANDLOCKED_CITIES:
        return []

    warnings: list[dict] = []
    seen: set[str] = set()
    for interest in interests:
        interest_lower = interest.strip().lower()
        for keyword, constraint in ACTIVITY_CONSTRAINTS.items():
            if keyword in interest_lower and constraint["label"] not in seen:
                req = constraint["requires"]
                if req == "coastal" and dest_lower in KNOWN_LANDLOCKED_CITIES:
                    seen.add(constraint["label"])
                    suggestion = CATEGORY_SUGGESTIONS.get(
                        keyword,
                        f"We've suggested local alternatives in {destination} instead.",
                    )
                    warnings.append({
                        "activity": constraint["label"],
                        "destination": destination,
                        "reason": constraint["reason_template"].format(
                            destination=destination
                        ),
                        "suggestion": suggestion,
                        "removed_names": [],
                    })
                elif req == "mountain_snow" and dest_lower in {
                    "jaipur", "goa", "mumbai", "chennai", "hyderabad", "kolkata",
                    "dubai", "singapore", "bangkok", "cairo", "nairobi",
                    "miami", "cape town", "rio de janeiro", "hanoi",
                }:
                    seen.add(constraint["label"])
                    warnings.append({
                        "activity": constraint["label"],
                        "destination": destination,
                        "reason": constraint["reason_template"].format(
                            destination=destination
                        ),
                        "suggestion": f"We've suggested local alternatives in {destination} instead.",
                        "removed_names": [],
                    })
    return warnings


def _strip_fake_activities(places: list[dict], destination: str) -> list[dict]:
    """Remove places whose names contain adventure/water-sport activities that
    are unlikely to be genuinely available at a lake or inland water body in a
    landlocked city. For example 'Jet Skiing at Hussain Sagar Lake'."""
    dest_lower = destination.strip().lower()
    if dest_lower not in KNOWN_LANDLOCKED_CITIES:
        return places
    cleaned = []
    for p in places:
        if not isinstance(p, dict):
            cleaned.append(p)
            continue
        name_lower = (p.get("name") or "").lower()
        tips_lower = (p.get("tips") or "").lower()
        is_fake = False
        for kw in FAKE_ACTIVITY_KEYWORDS:
            if kw in name_lower or kw in tips_lower:
                is_fake = True
                break
        if is_fake:
            print(f"[Guardrail] Stripped fabricated activity: '{p.get('name')}'")
        else:
            cleaned.append(p)
    return cleaned


async def filter_impossible_places(
    places: list[dict],
    destination: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Remove places whose name implies an activity impossible at the destination,
    and replace each with a real local alternative. Returns (final_places, removed, warnings)."""
    if destination.strip().lower() not in KNOWN_LANDLOCKED_CITIES:
        return places, [], []

    kept, removed = [], []
    matched_categories: set[str] = set()

    for p in places:
        if not isinstance(p, dict):
            kept.append(p)
            continue
        name_lower = (p.get("name") or "").lower()
        hit = None
        for kw in LANDLOCKED_KEYWORDS:
            if kw in name_lower:
                hit = kw
                break
        if hit:
            matched_categories.add(hit)
            removed.append(p)
        else:
            kept.append(p)

    if not removed:
        return places, [], []

    # Build warnings
    warnings: list[dict] = []
    seen_labels: set[str] = set()
    category_label_map = {
        "snorkel": "snorkeling", "surf": "surfing", "reef": "reef/coral",
        "coastal": "coastal", "seaside": "seaside", "ocean": "ocean",
    }
    for cat in matched_categories:
        label = category_label_map.get(cat, cat)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        names = [p.get("name", "Unknown") for p in removed if cat in (p.get("name") or "").lower()]
        warnings.append({
            "activity": label,
            "destination": destination,
            "reason": f"{label.capitalize()} activities aren't available in {destination} — it's a landlocked city with no coastline.",
            "suggestion": f"We've replaced them with real local alternatives like lakes, parks, and waterfront spots in {destination}.",
            "removed_names": names,
        })

    # Build set of existing place names for dedup
    existing_names = {(p.get("name") or "").lower() for p in kept if isinstance(p, dict)}
    next_id = max((int(p.get("id", "p0")[1:]) for p in places if isinstance(p, dict) and p.get("id", "").startswith("p")), default=0) + 1
    currency = ""
    if kept and isinstance(kept[0], dict):
        currency = kept[0].get("currency", "INR")

    # Get city center for distance validation
    center = _get_city_center(destination)
    center_lat = center[0] if center else None
    center_lng = center[1] if center else None

    replacement_prompt = (
        f"I removed {len(removed)} beach/ocean place(s) from a {destination} trip "
        f"because {destination} is landlocked: {', '.join(p.get('name', '?') for p in removed)}.\n\n"
        f"Suggest exactly {len(removed)} REPLACEMENT place(s) in {destination}.\n"
        f"CRITICAL RULES:\n"
        f"1. Every replacement MUST be a real, well-known WATER-RELATED spot — lakes, rivers, "
        f"reservoirs, dams, or boating spots that genuinely exist.\n"
        f"2. Do NOT invent or fabricate place names. Only suggest places that can be found on Google Maps.\n"
        f"3. Do NOT suggest any of these already-included places: {', '.join(existing_names)}.\n"
        f"4. Do NOT suggest cafes, museums, malls, hiking spots, or anything non-water.\n"
        f"5. Each place MUST be within 50 km of {destination} city center.\n\n"
        f"Return ONLY valid JSON — an array of {len(removed)} objects, each with:\n"
        f"- id (string, starting from 'p{next_id}')\n"
        f"- name (string, the real name as it appears on Google Maps)\n"
        f"- type (string: 'attraction' or 'activity')\n"
        f"- hours_needed (float)\n"
        f"- prereqs (array of strings)\n"
        f"- tips (string, mention it is a waterfront alternative)\n"
        f"- cost (float, in {currency})\n"
        f"- currency (string, '{currency}')\n"
        f"- lat (float, accurate latitude)\n"
        f"- lng (float, accurate longitude)\n"
    )

    try:
        llm = _get_feasibility_llm()
        raw = await asyncio.to_thread(llm.call, [{"role": "user", "content": replacement_prompt}])
        replacements = parse_llm_json(raw)
        if isinstance(replacements, dict) and "places" in replacements:
            replacements = replacements["places"]
        if not isinstance(replacements, list):
            replacements = [replacements] if isinstance(replacements, dict) else []

        added = []
        for r in replacements:
            if not isinstance(r, dict):
                continue
            if not r.get("name") or not r.get("id"):
                continue

            name_lower = (r["name"]).lower()

            # Skip duplicates of existing places
            if name_lower in existing_names:
                print(f"[Guardrail] Skipping duplicate replacement: {r['name']}")
                continue

            # Validate distance from city center
            r_lat = r.get("lat")
            r_lng = r.get("lng")
            if center_lat is not None and r_lat and r_lng:
                dist = _haversine_km(center_lat, center_lng, float(r_lat), float(r_lng))
                if dist > 50.0:
                    print(f"[Guardrail] Skipping replacement '{r['name']}' — {dist:.0f} km from city center")
                    continue

            r.setdefault("currency", currency)
            r.setdefault("type", "attraction")
            r.setdefault("hours_needed", 2.0)
            r.setdefault("prereqs", [])
            r.setdefault("tips", "")
            r.setdefault("cost", 0)
            r.setdefault("lat", 0)
            r.setdefault("lng", 0)
            existing_names.add(name_lower)
            kept.append(r)
            added.append(r.get("name"))
        print(f"[Guardrail] Replaced {len(removed)} impossible places with: {added}")
    except Exception as e:
        print(f"\033[1;33m⚠️  Replacement generation failed (non-fatal): {e}\033[0m")

    return kept, removed, warnings


# ---------------------------------------------------------------------------
# Guardrail: Geocoding fallback for city center when City Scout is skipped
# ---------------------------------------------------------------------------

CITY_CENTER_COORDS: dict[str, tuple[float, float]] = {
    "hyderabad": (17.3850, 78.4867),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.6139, 77.2090),
    "new delhi": (28.6139, 77.2090),
    "bangalore": (12.9716, 77.5946),
    "bengaluru": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "jaipur": (26.9124, 75.7873),
    "goa": (15.2993, 74.1240),
    "pune": (18.5204, 73.8567),
    "ahmedabad": (23.0225, 72.5714),
    "lucknow": (26.8467, 80.9462),
    "agra": (27.1767, 78.0081),
    "varanasi": (25.3176, 82.9739),
    "kochi": (9.9312, 76.2673),
    "udaipur": (24.5854, 73.7125),
    "amritsar": (31.6340, 74.8723),
    "paris": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
    "new york": (40.7128, -74.0060),
    "tokyo": (35.6762, 139.6503),
    "rome": (41.9028, 12.4964),
    "barcelona": (41.3874, 2.1686),
    "dubai": (25.2048, 55.2708),
    "singapore": (1.3521, 103.8198),
    "bangkok": (13.7563, 100.5018),
    "istanbul": (41.0082, 28.9784),
    "sydney": (-33.8688, 151.2093),
    "cairo": (30.0444, 31.2357),
    "berlin": (52.5200, 13.4050),
    "amsterdam": (52.3676, 4.9041),
    "lisbon": (38.7223, -9.1393),
    "prague": (50.0755, 14.4378),
    "vienna": (48.2082, 16.3738),
    "seoul": (37.5665, 126.9780),
    "kuala lumpur": (3.1390, 101.6869),
    "bali": (-8.3405, 115.0920),
    "hanoi": (21.0278, 105.8342),
    "mexico city": (19.4326, -99.1332),
    "rio de janeiro": (-22.9068, -43.1729),
    "cape town": (-33.9249, 18.4241),
    "nairobi": (-1.2921, 36.8219),
    "marrakech": (31.6295, -7.9811),
}


def _get_city_center(destination: str, places: list[dict] | None = None) -> tuple[float, float] | None:
    """Return (lat, lng) for a city center. Tries:
    1. Static lookup table (instant)
    2. Median of the LLM-suggested places (good approximation)
    """
    key = destination.strip().lower()
    if key in CITY_CENTER_COORDS:
        return CITY_CENTER_COORDS[key]

    if places:
        lats, lngs = [], []
        for p in places:
            if isinstance(p, dict) and p.get("lat") is not None and p.get("lng") is not None:
                lats.append(float(p["lat"]))
                lngs.append(float(p["lng"]))
        if len(lats) >= 3:
            lats.sort()
            lngs.sort()
            mid = len(lats) // 2
            return (lats[mid], lngs[mid])

    return None


# ---------------------------------------------------------------------------
# Guardrail: Distance Filter (>50 km from city center)
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two points in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_distant_places(
    places: list[dict],
    center_lat: float,
    center_lng: float,
    max_km: float = 50.0,
) -> tuple[list[dict], list[dict]]:
    """Split places into (kept, removed) based on distance from city center."""
    kept, removed = [], []
    for p in places:
        if not isinstance(p, dict):
            kept.append(p)
            continue
        lat = p.get("lat")
        lng = p.get("lng")
        if lat is None or lng is None:
            kept.append(p)
            continue
        dist = _haversine_km(center_lat, center_lng, lat, lng)
        if dist > max_km:
            removed.append({**p, "_distance_km": round(dist, 1)})
        else:
            kept.append(p)
    return kept, removed


def _redistribute_blocks(days: list, num_days_requested: int) -> list:
    """Safety net for when the LLM ignores our distribution rules and piles
    every block into a single day. If most days are empty but we have plenty
    of blocks elsewhere, chunk them evenly across the requested day count.

    Heuristic-only (no LLM call): we fan out the blocks round-robin and
    re-time each chunk on a sensible 9am/12pm/3pm/6pm grid. The user can
    always Refine for nicer pacing — this just guarantees no day feels
    abandoned.
    """
    if num_days_requested <= 1:
        return days

    all_blocks = []
    for d in days:
        for b in (d.get("blocks") or []):
            if isinstance(b, dict):
                all_blocks.append(b)

    if len(all_blocks) < 2:
        return days

    non_empty_days = sum(1 for d in days if (d.get("blocks") or []))
    # Only redistribute when distribution is clearly broken (≤ 1 day with
    # any content despite multiple days requested AND multiple blocks
    # available).
    if non_empty_days >= 2:
        return days

    chunks: list[list] = [[] for _ in range(num_days_requested)]
    for idx, b in enumerate(all_blocks):
        chunks[idx % num_days_requested].append(b)

    fallback_slots = ["09:00 AM", "12:00 PM", "03:00 PM", "06:00 PM", "08:00 PM"]
    fallback_ends = ["11:30 AM", "02:00 PM", "05:00 PM", "07:30 PM", "09:30 PM"]

    new_days = []
    for di, chunk in enumerate(chunks):
        retimed = []
        for bi, block in enumerate(chunk):
            new_block = dict(block)
            slot = bi if bi < len(fallback_slots) else len(fallback_slots) - 1
            new_block["start"] = fallback_slots[slot]
            new_block["end"] = fallback_ends[slot]
            retimed.append(new_block)
        new_days.append({
            "day": di + 1,
            "theme": (days[di].get("theme") if di < len(days) else None) or "Day {} explorations".format(di + 1),
            "blocks": retimed,
        })
    return new_days


def _dedup_itinerary_blocks(days: list) -> list:
    """Remove duplicate place_id references across the entire itinerary.
    Keeps the first occurrence and drops subsequent ones."""
    seen: set[str] = set()
    for d in days:
        blocks = d.get("blocks") or []
        deduped = []
        for b in blocks:
            pid = b.get("place_id")
            if pid and pid in seen:
                print(f"[Guardrail] Removed duplicate place_id '{pid}' from day {d.get('day')}")
                continue
            if pid:
                seen.add(pid)
            deduped.append(b)
        d["blocks"] = deduped
    return days


def _cap_blocks_per_day(days: list, max_blocks: int = 3) -> list:
    """Enforce a maximum number of blocks per day. Overflow blocks are
    moved to subsequent days that have room, keeping the itinerary balanced."""
    overflow: list[dict] = []
    for d in days:
        blocks = d.get("blocks") or []
        if len(blocks) > max_blocks:
            overflow.extend(blocks[max_blocks:])
            d["blocks"] = blocks[:max_blocks]

    # Try to place overflow into days with fewer than max_blocks
    for b in overflow:
        placed = False
        for d in days:
            if len(d.get("blocks") or []) < max_blocks:
                d["blocks"].append(b)
                placed = True
                break
        if not placed:
            print(f"[Guardrail] Dropped overflow block '{b.get('place_id')}' — all days full")
    return days


def hydrate_itinerary(
    itinerary: dict,
    places: list,
    *,
    start_date_str: str | None,
    num_days_requested: int,
    local_currency: str,
    user_currency: str,
) -> dict:
    """Augment a raw concierge itinerary with calendar dates, dual-currency
    costs, and padding so the frontend can render it without conditional
    null checks. Mutates and returns the input dict.

    Shared by the initial /plan run and the /refine re-plan so both code
    paths produce identically-shaped output (including total_cost_user,
    per-block currency, etc).
    """
    if not isinstance(itinerary, dict):
        itinerary = {"days": []}

    itinerary["currency"] = local_currency
    itinerary["currency_user"] = user_currency

    try:
        start_date_obj = datetime.strptime(start_date_str or "", "%Y-%m-%d")
    except Exception:
        start_date_obj = datetime.now()

    existing_days = itinerary.get("days") or []

    # Safety nets
    existing_days = _redistribute_blocks(existing_days, num_days_requested)
    existing_days = _dedup_itinerary_blocks(existing_days)
    existing_days = _cap_blocks_per_day(existing_days, max_blocks=3)

    if num_days_requested and len(existing_days) < num_days_requested:
        for missing_idx in range(len(existing_days), num_days_requested):
            existing_days.append({
                "day": missing_idx + 1,
                "theme": "Free day",
                "blocks": [],
            })
    itinerary["days"] = existing_days

    total_cost_local = 0.0
    total_cost_user = 0.0
    for idx, day in enumerate(itinerary.get("days", [])):
        if "date" not in day:
            day["date"] = (start_date_obj + timedelta(days=idx)).strftime("%Y-%m-%d")

        day_cost_local = 0.0
        day_cost_user = 0.0
        for block in day.get("blocks", []):
            p_id = block.get("place_id")
            place = next(
                (
                    p for p in places
                    if (p.get("id") if isinstance(p, dict) else getattr(p, "id", None)) == p_id
                ),
                None,
            )
            if place:
                place_cost = place.get("cost", 0) if isinstance(place, dict) else getattr(place, "cost", 0)
                place_cost_user = (
                    place.get("cost_user", convert_currency(place_cost, local_currency, user_currency))
                    if isinstance(place, dict)
                    else convert_currency(place_cost, local_currency, user_currency)
                )
                block["item"] = place.get("name", "Unknown") if isinstance(place, dict) else getattr(place, "name", "Unknown")
                block["type"] = place.get("type", "activity") if isinstance(place, dict) else getattr(place, "type", "activity")
                block["cost"] = place_cost
                block["currency"] = local_currency
                block["cost_user"] = place_cost_user
                block["currency_user"] = user_currency
                day_cost_local += float(place_cost or 0)
                day_cost_user += float(place_cost_user or 0)
            else:
                block["item"] = "Unknown"
                block["type"] = "activity"
                block["cost"] = 0
                block["currency"] = local_currency
                block["cost_user"] = 0
                block["currency_user"] = user_currency

            if "end" not in block:
                block["end"] = "TBD"

        day["day_cost"] = round(day_cost_local, 2)
        day["day_cost_user"] = round(day_cost_user, 2)
        total_cost_local += day_cost_local
        total_cost_user += day_cost_user

    itinerary["total_cost"] = round(total_cost_local, 2)
    itinerary["total_cost_user"] = round(total_cost_user, 2)
    return itinerary


class TripOrchestrator:
    """
    Agentic Orchestrator to manage the execution of CrewAI tasks and crews.
    This cleanly separates AI reasoning and parallel execution logic from the 
    FastAPI HTTP streaming layer.
    """

    MAX_RETRIES = 3
    RETRY_BACKOFF = [10, 20, 40]

    @staticmethod
    def _kickoff_with_log(crew: Crew, agent_name: str):
        """Run a Crew with automatic retry on rate-limit (429) errors."""
        print(f"\n\033[1;35m{'='*60}\033[0m")
        print(f"\033[1;36m🚀 [DEMO TRACE] Agent Started : {agent_name}\033[0m")
        print(f"\033[1;35m{'='*60}\033[0m\n")

        start_t = time.time()
        last_err = None

        for attempt in range(TripOrchestrator.MAX_RETRIES):
            try:
                result = crew.kickoff()
                elapsed = time.time() - start_t
                print(f"\n\033[1;35m{'='*60}\033[0m")
                print(f"\033[1;32m✅ [DEMO TRACE] Agent Finished: {agent_name}\033[0m")
                print(f"\033[1;33m⏱️  Execution Time : {elapsed:.2f} seconds\033[0m")
                print(f"\033[1;35m{'='*60}\033[0m\n")
                return result
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                is_rate_limit = "429" in err_str or "rate" in err_str or "capacity" in err_str
                if not is_rate_limit or attempt == TripOrchestrator.MAX_RETRIES - 1:
                    raise
                wait = TripOrchestrator.RETRY_BACKOFF[attempt]
                print(f"\033[1;33m⚠️  [{agent_name}] Rate-limited (attempt {attempt + 1}/{TripOrchestrator.MAX_RETRIES}), retrying in {wait}s…\033[0m")
                time.sleep(wait)

        raise last_err
    
    @staticmethod
    async def select_cities(data: dict) -> list:
        city_task = create_city_selection_task(data)
        city_crew = Crew(
            agents=[city_selection_agent],
            tasks=[city_task],
            verbose=True
        )
        await asyncio.to_thread(TripOrchestrator._kickoff_with_log, city_crew, "City Selection Expert")
        suggestion_str = city_task.output.raw
        return parse_llm_json(suggestion_str).get("suggestions", [])

    @staticmethod
    async def execute_local_and_flight(destination: str, data: dict, skip_flight: bool = False) -> tuple[list, dict | None, str]:
        exec_data = dict(data)
        exec_data["destination"] = destination
        
        l_task = create_local_expert_task(exec_data)
        l_crew = Crew(agents=[local_expert_agent], tasks=[l_task], verbose=True)
        
        origin = exec_data.get("origin") or ""
        user_curr = (exec_data.get("budget", {}) or {}).get("currency", "USD") or "USD"
        user_curr = user_curr.upper()
        
        f_task = None
        f_crew = None
        if not skip_flight and origin and origin.strip().lower() != destination.strip().lower():
            f_task = create_flight_estimation_task(origin, destination, user_curr)
            f_crew = Crew(agents=[flight_expert_agent], tasks=[f_task], verbose=True)
            
        calls = [asyncio.to_thread(TripOrchestrator._kickoff_with_log, l_crew, f"Local Expert ({destination})")]
        if f_crew:
            calls.append(asyncio.to_thread(TripOrchestrator._kickoff_with_log, f_crew, f"Flight Pricing Expert ({destination})"))
            
        results = await asyncio.gather(*calls, return_exceptions=True)

        # Check if Local Expert failed — that's fatal
        if isinstance(results[0], Exception):
            print(f"\033[1;31m❌ Local Expert failed: {results[0]}\033[0m")
            raise results[0]

        # Flight Expert failure is non-fatal — just log and skip
        if len(results) > 1 and isinstance(results[1], Exception):
            print(f"\033[1;33m⚠️  Flight Expert failed (non-fatal): {results[1]}\033[0m")

        # Parse local expert output
        p_local = parse_llm_json(l_task.output.raw)
        s_places = p_local.get("places", [])
        l_curr = (p_local.get("currency") or "").upper()
        
        if not l_curr and s_places and isinstance(s_places[0], dict):
            l_curr = (s_places[0].get("currency") or "").upper()
        if not l_curr:
            l_curr = user_curr
            
        for p in s_places:
            if isinstance(p, dict):
                p.setdefault("currency", l_curr)
                p["cost_user"] = convert_currency(p.get("cost", 0), p.get("currency", l_curr), user_curr)
                p["currency_user"] = user_curr
                
        # Parse flight expert output (skip if agent failed)
        est_flight_cost = None
        if f_task and f_task.output and not (len(results) > 1 and isinstance(results[1], Exception)):
            try:
                p_flight = parse_llm_json(f_task.output.raw)
                c_flight = p_flight.get("est_flight_cost")
                if (
                    isinstance(c_flight, dict) 
                    and isinstance(c_flight.get("low"), (int, float)) 
                    and isinstance(c_flight.get("high"), (int, float))
                ):
                    est_flight_cost = {
                        "low": float(c_flight["low"]),
                        "high": float(c_flight["high"]),
                        "currency": (c_flight.get("currency") or user_curr).upper(),
                    }
            except Exception as e:
                print(f"\033[1;33m⚠️  Flight cost parse failed (non-fatal): {e}\033[0m")
                
        return s_places, est_flight_cost, l_curr

    @staticmethod
    async def enrich_city_suggestion(sugg: dict, data: dict) -> dict:
        destination = sugg.get("city", "Unknown")
        try:
            s_places, est_flight, _ = await TripOrchestrator.execute_local_and_flight(destination, data)
            sugg["places"] = s_places
            if est_flight:
                sugg["est_flight_cost"] = est_flight
        except Exception as e:
            print(f"\033[1;33m⚠️  Enrichment failed for {destination} (non-fatal): {e}\033[0m")
            sugg.setdefault("places", [])
        return sugg

    @staticmethod
    async def enrich_all_suggestions(suggestions: list, data: dict) -> list:
        return await asyncio.gather(*(TripOrchestrator.enrich_city_suggestion(s, data) for s in suggestions))

    @staticmethod
    async def plan_itinerary(data: dict) -> dict:
        concierge_task = create_travel_concierge_task(data)
        concierge_crew = Crew(agents=[travel_concierge_agent], tasks=[concierge_task], verbose=True)
        await asyncio.to_thread(TripOrchestrator._kickoff_with_log, concierge_crew, "Travel Concierge")
        
        parsed_itinerary = parse_llm_json(concierge_task.output.raw)
        itinerary = parsed_itinerary.get("itinerary", {"days": []})
        return {"days": itinerary} if isinstance(itinerary, list) else itinerary

    @staticmethod
    async def determine_refinement_route(refinement: str) -> str:
        """
        Uses the LLM to decide if a refinement request requires finding new places
        or just re-organizing the existing ones.
        """
        prompt = (
            "Analyze the following travel itinerary refinement request:\n"
            f"\"{refinement}\"\n\n"
            "Determine if the user is asking for NEW types of places/activities that "
            "weren't in the original list (e.g., 'add a museum', 'find me some vegan spots') "
            "or if they are just re-organizing existing ones (e.g., 'make day 2 less walking', "
            "'move the park to the morning').\n\n"
            "Return ONLY one of these two strings:\n"
            "FETCH_NEW_PLACES - if new places or specific new interests are requested.\n"
            "REARRANGE_EXISTING - if the request is about timing, pacing, or ordering.\n"
        )
        
        from crewai import LLM
        import os
        
        # Initialize the LLM to fix the NameError
        mistral_llm = LLM(
            model="mistral/mistral-small-latest",
            api_key=os.getenv("MISTRAL_API_KEY"),
            temperature=0.1
        )
        
        print(f"\n\033[1;35m{'='*60}\033[0m")
        print(f"\033[1;36m🧠 [DEMO TRACE] Router Agent Started: Analyzing Request\033[0m")
        print(f"\033[1;35m{'='*60}\033[0m\n")
        
        start_t = time.time()
        response = mistral_llm.call([{"role": "user", "content": prompt}])
        elapsed = time.time() - start_t
        
        print(f"\n\033[1;35m{'='*60}\033[0m")
        print(f"\033[1;32m✅ [DEMO TRACE] Router Agent Finished\033[0m")
        print(f"\033[1;33m⏱️  Execution Time : {elapsed:.2f} seconds\033[0m")
        print(f"\033[1;35m{'='*60}\033[0m\n")
        
        if response and "FETCH_NEW_PLACES" in response:
            return "FETCH_NEW_PLACES"
        return "REARRANGE_EXISTING"

    @staticmethod
    async def refine_itinerary(inputs: dict) -> str:
        refine_task = create_travel_concierge_task(inputs)
        refine_crew = Crew(agents=[travel_concierge_agent], tasks=[refine_task], verbose=True)
        await asyncio.to_thread(TripOrchestrator._kickoff_with_log, refine_crew, "Travel Concierge (Refinement)")
        return refine_task.output.raw

app = FastAPI(title="Bon Voyage API", version="1.0.0")

# Allow frontend to call backend - updated for production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://*.vercel.app",
        "https://bonvoyage.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Bon Voyage API is running", "status": "healthy"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}

def unwrap_a2a(payload: dict) -> dict:
    """If *payload* is an A2A JSON-RPC envelope, extract the inner plan data.

    The MuleSoft Omni Gateway enforces A2A Schema Validation on the Travel
    Concierge route, so the frontend wraps the structured plan/refine data
    inside `params.message.parts`.  We look for a part with `type: "data"`,
    falling back to JSON-parsing the first `type: "text"` part.
    """
    if "jsonrpc" not in payload or "params" not in payload:
        return payload
    try:
        parts = payload["params"]["message"]["parts"]
        for p in parts:
            if p.get("type") == "data" and isinstance(p.get("data"), dict):
                return p["data"]
        for p in parts:
            if p.get("type") == "text":
                try:
                    return json.loads(p["text"])
                except (json.JSONDecodeError, TypeError):
                    pass
    except (KeyError, TypeError):
        pass
    return payload


@app.post("/plan")
async def plan_trip(request: Request):
    raw_payload = await request.json()
    data = unwrap_a2a(raw_payload)
    print("Incoming request payload:", data)

    async def event_stream():
        run_id = str(uuid.uuid4())
        # 1. Send the initial run.start event
        yield f"data: {json.dumps({'type': 'run.start', 'data': {'run_id': run_id}})}\n\n"
        await asyncio.sleep(0.1)
        
        task = {"inputs": data}
        chosen_destination = data.get("destination")
        chosen_suggestion = None
        
        try:
            places = data.get("places", [])
            
            # --- 1. City Selection ---
            if not chosen_destination:
                # Notify frontend the City Selection agent is running
                yield f"data: {json.dumps({'type': 'agent.start', 'data': {'agent': 'city_selection'}})}\n\n"
                start_t = time.time()
                
                suggestions = await TripOrchestrator.select_cities(data)
                    
                yield f"data: {json.dumps({'type': 'agent.output.city_selection', 'data': {'suggestions': suggestions}})}\n\n"
                
                elapsed = int((time.time() - start_t) * 1000)
                yield f"data: {json.dumps({'type': 'agent.done', 'data': {'agent': 'city_selection', 'elapsed_ms': elapsed}})}\n\n"

                # -----------------------------------------------------------------
                # NEW: Run Local Expert & Flight Expert for ALL suggestions concurrently
                # -----------------------------------------------------------------
                if suggestions:
                    yield f"data: {json.dumps({'type': 'agent.start', 'data': {'agent': 'local_expert'}})}\n\n"
                    le_start_t = time.time()
                    
                    # Await all parallel enrichment pipelines via Orchestrator
                    suggestions = await TripOrchestrator.enrich_all_suggestions(suggestions, data)
                    
                    elapsed_le = int((time.time() - le_start_t) * 1000)
                    yield f"data: {json.dumps({'type': 'agent.done', 'data': {'agent': 'local_expert', 'elapsed_ms': elapsed_le}})}\n\n"

                # If the user requested multiple destination options, pause the run here 
                # so they can pick one. Suggestions now have `places` attached!
                num_suggestions_requested = int(data.get("num_suggestions") or 1)
                if num_suggestions_requested > 1 and len(suggestions) > 1:
                    yield f"data: {json.dumps({'type': 'agent.awaiting_selection', 'data': {'suggestions': suggestions}})}\n\n"
                    return

                # Otherwise auto-select the top suggestion
                if suggestions:
                    chosen_suggestion = suggestions[0]
                    chosen_destination = suggestions[0].get("city")
                    places = chosen_suggestion.get("places", [])
                    data["places"] = places
            else:
                # --- Pass 2: Destination Locked ---
                yield f"data: {json.dumps({'type': 'agent.skip', 'data': {'agent': 'city_selection', 'reason': 'destination locked'}})}\n\n"
                forwarded = data.get("chosen_suggestion") if isinstance(data.get("chosen_suggestion"), dict) else None
                if forwarded:
                    chosen_suggestion = {
                        "city": forwarded.get("city") or chosen_destination,
                        "country": forwarded.get("country") or "",
                        "weather_summary": forwarded.get("weather_summary") or "",
                        "est_flight_cost": forwarded.get("est_flight_cost") or {
                            "low": 0,
                            "high": 0,
                            "currency": data.get("budget", {}).get("currency", "USD"),
                        },
                        "score": forwarded.get("score") if forwarded.get("score") is not None else 1.0,
                        "rationale": forwarded.get("rationale") or "User selected destination.",
                        **({"hero_image": forwarded["hero_image"]} if forwarded.get("hero_image") else {}),
                        **({"center": forwarded["center"]} if forwarded.get("center") else {}),
                        "places": forwarded.get("places", [])  # PRESERVE places from payload
                    }
                    if not data.get("places") and chosen_suggestion.get("places"):
                        data["places"] = chosen_suggestion["places"]
                else:
                    chosen_suggestion = {
                        "city": chosen_destination,
                        "country": "",
                        "weather_summary": "",
                        "est_flight_cost": {"low": 0, "high": 0, "currency": data.get("budget", {}).get("currency", "USD")},
                        "score": 1.0,
                        "rationale": "User selected destination.",
                    }

            # --- 2. Local Expert ---
            places = data.get("places", [])
            user_currency = (data.get("budget", {}) or {}).get("currency", "USD") or "USD"
            user_currency = user_currency.upper()
            
            # Only execute Local Expert fallback if places weren't passed through or fetched above
            if not places:
                data["destination"] = chosen_destination
                yield f"data: {json.dumps({'type': 'agent.start', 'data': {'agent': 'local_expert'}})}\n\n"
                start_t = time.time()
    
                places, est_flight_cost, local_currency = await TripOrchestrator.execute_local_and_flight(chosen_destination, data)
                
                if est_flight_cost:
                    chosen_suggestion["est_flight_cost"] = est_flight_cost
    
                elapsed = int((time.time() - start_t) * 1000)
                yield f"data: {json.dumps({'type': 'agent.done', 'data': {'agent': 'local_expert', 'elapsed_ms': elapsed}})}\n\n"
            elif chosen_destination and data.get("chosen_suggestion"):
                # If we entered Pass 2 and already had places loaded, we seamlessly skip!
                yield f"data: {json.dumps({'type': 'agent.skip', 'data': {'agent': 'local_expert', 'reason': 'places already generated in previous step'}})}\n\n"

            # Strip fabricated activities before showing to user
            if chosen_destination:
                places = _strip_fake_activities(places, chosen_destination)

            # Guarantee output is triggered for frontend UX
            yield f"data: {json.dumps({'type': 'agent.output.local_expert', 'data': {'places': places}})}\n\n"

            local_currency = ""
            if places and isinstance(places[0], dict):
                local_currency = (places[0].get("currency") or "").upper()
            if not local_currency:
                local_currency = user_currency

            # Guardrail: Category Filter — catch semantically impossible places
            activity_warnings: list[dict] = []
            if chosen_destination:
                places, impossible_places, activity_warnings = await filter_impossible_places(places, chosen_destination)
                if impossible_places:
                    print(f"[Guardrail] Removed {len(impossible_places)} impossible places: {[p.get('name') for p in impossible_places]}")
                    for p in places:
                        if isinstance(p, dict) and "cost_user" not in p:
                            p.setdefault("currency", local_currency)
                            p["cost_user"] = convert_currency(p.get("cost", 0), p.get("currency", local_currency), user_currency)
                            p["currency_user"] = user_currency

                # Also check user interests for impossible activities even
                # when the LLM correctly avoided generating such places
                interest_warnings = _check_interests_feasibility(
                    data.get("interests", []), chosen_destination
                )
                if interest_warnings:
                    warned_activities = {w["activity"] for w in activity_warnings}
                    for iw in interest_warnings:
                        if iw["activity"] not in warned_activities:
                            activity_warnings.append(iw)
                            print(f"[Guardrail] Interest warning: '{iw['activity']}' not feasible in {chosen_destination}")

            # Guardrail: Distance Filter — remove places >50km from city center
            center = (chosen_suggestion or {}).get("center")
            c_lat, c_lng = None, None
            if center and isinstance(center, dict):
                c_lat = center.get("lat")
                c_lng = center.get("lng")

            if c_lat is None or c_lng is None:
                fallback = _get_city_center(chosen_destination or "", places)
                if fallback:
                    c_lat, c_lng = fallback
                    print(f"[Guardrail] Using fallback center for '{chosen_destination}': ({c_lat}, {c_lng})")

            distance_removed: list[dict] = []
            if c_lat is not None and c_lng is not None:
                places, distance_removed = filter_distant_places(places, c_lat, c_lng, max_km=50.0)
                if distance_removed:
                    print(f"[Guardrail] Removed {len(distance_removed)} distant places: {[p.get('name') for p in distance_removed]}")
                    data["places"] = places

            # Emit guardrail events — the frontend shows these inline in the Local Guide section
            if activity_warnings:
                yield f"data: {json.dumps({'type': 'guardrail.activity_warning', 'data': {'warnings': activity_warnings}})}\n\n"
            if distance_removed:
                yield f"data: {json.dumps({'type': 'guardrail.distance_filter', 'data': {'removed': distance_removed}})}\n\n"

            # Re-emit the cleaned places so the frontend updates its grid
            if activity_warnings or distance_removed:
                yield f"data: {json.dumps({'type': 'agent.output.local_expert', 'data': {'places': places}})}\n\n"

            # --- 3. Travel Concierge ---
            # Provide the generated places into the inputs for the Concierge
            data["places"] = places

            yield f"data: {json.dumps({'type': 'agent.start', 'data': {'agent': 'travel_concierge'}})}\n\n"
            start_t = time.time()

            itinerary = await TripOrchestrator.plan_itinerary(data)

            yield f"data: {json.dumps({'type': 'agent.output.travel_concierge', 'data': {'itinerary': itinerary}})}\n\n"

            elapsed = int((time.time() - start_t) * 1000)
            yield f"data: {json.dumps({'type': 'agent.done', 'data': {'agent': 'travel_concierge', 'elapsed_ms': elapsed}})}\n\n"

            # --- 4. End the stream gracefully ---
            # We finally have everything! Construct the final trip object and send the complete event.

            itinerary = hydrate_itinerary(
                itinerary,
                places,
                start_date_str=data.get("start_date"),
                num_days_requested=int(data.get("num_days") or 0),
                local_currency=local_currency,
                user_currency=user_currency,
            )

            final_trip = {
                "run_id": run_id,
                "brief": data,
                "chosen": chosen_suggestion,
                "places": places,
                "itinerary": itinerary
            }
            yield f"data: {json.dumps({'type': 'run.complete', 'data': {'trip': final_trip}})}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'type': 'run.error', 'data': {'message': str(e)}})}\n\n"

    # Return the generator as a Server-Sent Events stream
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/refine")
async def refine_trip(request: Request):
    """Re-run the Travel Concierge against an already-built trip with a
    natural-language refinement instruction (e.g. "make day 2 less walking",
    "swap museums for outdoor activities"). Reuses the existing places and
    brief — only the itinerary is regenerated.

    Returns a plain JSON response (not SSE) since only one agent runs and
    the drawer UX shows a single pending state.
    """
    raw_payload = await request.json()
    data = unwrap_a2a(raw_payload)
    print("Incoming /refine payload:", {k: v for k, v in data.items() if k != "places"})

    refinement = (data.get("refinement") or "").strip()
    if not refinement:
        return JSONResponse({"error": "refinement instruction is required"}, status_code=400)

    brief = data.get("brief") or {}
    places = data.get("places") or []
    current_itinerary = data.get("itinerary") or {}

    destination = brief.get("destination") or ""
    user_currency = ((brief.get("budget") or {}).get("currency") or "USD").upper()
    local_currency = (current_itinerary.get("currency") or user_currency).upper()
    num_days = int(brief.get("num_days") or len(current_itinerary.get("days") or []) or 1)

    inputs = {
        "destination": destination,
        "num_days": num_days,
        "places": places,
        "refinement": refinement,
        "current_itinerary": current_itinerary,
    }

    try:
        # 0. Guardrail: check for geographically impossible activities
        warning = await check_activity_feasibility(refinement, destination)
        if warning:
            print(f"[Guardrail] Blocked refinement: {warning}")
            return JSONResponse({
                "guardrail": warning,
                "error": None,
                "itinerary": None,
            }, status_code=200)

        # 1. Agentic Routing: Let the LLM decide the execution path!
        route = await TripOrchestrator.determine_refinement_route(refinement)
        print(f"[Agentic Router] Decided route: {route}")
        
        # 2. Autonomous Branching
        if route == "FETCH_NEW_PLACES":
            # Temporarily inject the refinement as 'special_requirements' to guide the Local Expert
            brief_copy = dict(brief)
            brief_copy["special_requirements"] = refinement
            
            # Spin up the Local Expert to find the newly requested places
            new_places, _, _ = await TripOrchestrator.execute_local_and_flight(destination, brief_copy, skip_flight=True)
            
            # Merge the new places with the old ones so the Concierge has access to them
            # FIX: The Local Expert resets IDs to 'p1', 'p2', etc. which collide with existing IDs.
            # We must filter by name to find genuinely new places, give them fresh IDs, and append.
            existing_names = {p.get("name", "").lower().strip() for p in places if isinstance(p, dict)}
            import uuid
            for np in new_places:
                if isinstance(np, dict):
                    np_name = np.get("name", "").lower().strip()
                    if np_name and np_name not in existing_names:
                        np["id"] = f"refine_{uuid.uuid4().hex[:6]}"
                        places.append(np)
                        existing_names.add(np_name) # Prevent duplicates within the new batch
            inputs["places"] = places

        # 3. Final Itinerary Generation
        raw = await TripOrchestrator.refine_itinerary(inputs)
        
        parsed = parse_llm_json(raw)
        new_itinerary = parsed.get("itinerary", {"days": []})
        if isinstance(new_itinerary, list):
            new_itinerary = {"days": new_itinerary}

        new_itinerary = hydrate_itinerary(
            new_itinerary,
            places,
            start_date_str=brief.get("start_date"),
            num_days_requested=num_days,
            local_currency=local_currency,
            user_currency=user_currency,
        )
        return {"itinerary": new_itinerary}
    except Exception as e:
        print(f"[refine] failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)
