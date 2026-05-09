"""OpenStreetMap / Overpass API service for location-based healthcare search.

Uses the public Overpass API (https://overpass-api.de) to query nearby
healthcare facilities and emergency services from OpenStreetMap data.

This is a free alternative to Google Maps Places API with no API key required.
For production at scale, consider self-hosting Overpass or using a paid
OSM provider such as Geoapify.
"""

from __future__ import annotations

import logging
from math import asin, cos, radians, sin, sqrt
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Public Overpass API endpoints — tried in order, rotates on 429/504
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",  # primary
    "https://overpass.kumi.systems/api/interpreter",  # fallback 1
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",  # fallback 2
]
REQUEST_TIMEOUT = 15  # seconds

# ---------------------------------------------------------------------------
# Specialty → OSM amenity/healthcare tag mapping
# Maps common user-facing specialty terms to the most precise OSM tag so
# the Overpass query targets that node type directly instead of returning
# every healthcare facility and hoping the agent filters.
# ---------------------------------------------------------------------------
SPECIALTY_OSM_TAGS: dict[str, list[str]] = {
    # Dental
    "dentist": ["dentist"],
    "dental": ["dentist"],
    "tooth": ["dentist"],
    "teeth": ["dentist"],
    "orthodontist": ["dentist"],
    # Pharmacy
    "pharmacy": ["pharmacy"],
    "chemist": ["pharmacy"],
    "medicine": ["pharmacy"],
    # Hospital / emergency
    "hospital": ["hospital"],
    "emergency": ["hospital"],
    # Eye
    "optometrist": ["doctors", "clinic"],
    "ophthalmologist": ["doctors", "clinic"],
    "eye": ["doctors", "clinic"],
    # General
    "doctor": ["doctors", "clinic", "health_centre"],
    "gp": ["doctors", "clinic"],
    "general practitioner": ["doctors", "clinic"],
    "clinic": ["clinic", "health_centre"],
}

# ---------------------------------------------------------------------------
# Emergency phone numbers by ISO 3166-1 alpha-2 country code
# ---------------------------------------------------------------------------
EMERGENCY_NUMBERS: dict[str, str] = {
    "US": "911",
    "CA": "911",
    "MX": "911",
    "GB": "999",
    "IE": "999",
    "AU": "000",
    "NZ": "111",
    "DE": "112",
    "FR": "15",  # SAMU (medical); 18 for fire, 17 for police
    "ES": "112",
    "IT": "118",
    "PT": "112",
    "NL": "112",
    "BE": "112",
    "CH": "144",
    "AT": "144",
    "SE": "112",
    "NO": "113",
    "DK": "112",
    "FI": "112",
    "PL": "112",
    "RU": "103",
    "IN": "112",
    "CN": "120",
    "JP": "119",
    "KR": "119",
    "PK": "1122",
    "BD": "999",
    "GH": "112",
    "NG": "112",
    "ZA": "10177",
    "KE": "999",
    "TZ": "112",
    "UG": "999",
    "EG": "123",
    "MA": "15",
    "BR": "192",
    "AR": "107",
    "CL": "131",
    "CO": "125",
    "SA": "997",
    "AE": "998",
    "QA": "999",
    "DEFAULT": "112",  # Pan-European / international standard
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _maps_link(name: str, latitude: float, longitude: float) -> str:
    """Generate a Google Maps search URL for a facility.

    Opens a Google Maps search centred on the facility's coordinates with its
    name pre-filled, so users can see reviews, phone, opening hours, and
    directions without needing a Google API key.
    """
    from urllib.parse import quote

    query = quote(f"{name}")
    return f"https://www.google.com/maps/search/?api=1&query={query}&center={latitude},{longitude}"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two GPS points."""
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _parse_element(el: dict, user_lat: float, user_lon: float) -> Optional[dict]:
    """Parse a single Overpass API element into a clean result dict.

    Returns None if the element lacks a name or coordinates.
    """
    tags = el.get("tags", {})
    name = tags.get("name")
    if not name:
        return None

    # Nodes have lat/lon directly; ways have them under 'center'
    lat = el.get("lat") or (el.get("center") or {}).get("lat")
    lon = el.get("lon") or (el.get("center") or {}).get("lon")
    if lat is None or lon is None:
        return None

    distance_km = _haversine_km(user_lat, user_lon, lat, lon)

    # Build a human-readable address from OSM address tags
    addr_parts = []
    for key in ("addr:housenumber", "addr:street", "addr:suburb", "addr:city"):
        val = tags.get(key)
        if val:
            addr_parts.append(val)
    address = ", ".join(addr_parts) or tags.get("addr:full") or None

    # Phone: try multiple common OSM tag keys
    phone = (
        tags.get("phone")
        or tags.get("contact:phone")
        or tags.get("telephone")
        or tags.get("emergency:phone")
    )

    # Website: try multiple common OSM tag keys
    website = tags.get("website") or tags.get("contact:website") or tags.get("url")

    # Specialty from OSM healthcare:speciality tag
    specialty = (
        tags.get("healthcare:speciality")
        or tags.get("healthcare:specialty")
        or tags.get("medical_system:western")
    )

    # Operator name (e.g. "NHS", "Apollo", private owner name)
    operator = tags.get("operator") or tags.get("brand")

    # Description tag
    description = tags.get("description") or tags.get("note")

    # Always generate a Google Maps link — gives phone, reviews, hours
    # even when OSM has none of that data
    gmaps_link = _maps_link(name, lat, lon)

    # Booking contact: phone is preferred, fallback to website, then Google Maps
    if phone:
        booking_contact = f"Call to book: {phone}"
    elif website:
        booking_contact = f"Book online: {website}"
    else:
        booking_contact = f"Find contact & reviews: {gmaps_link}"

    return {
        "name": name,
        "type": tags.get("amenity") or tags.get("healthcare") or "healthcare",
        "specialty": specialty,
        "operator": operator,
        "description": description,
        "address": address,
        "phone": phone,
        "website": website,
        "maps_link": gmaps_link,
        "opening_hours": tags.get("opening_hours"),
        "distance_km": round(distance_km, 2),
        "latitude": lat,
        "longitude": lon,
        "booking_contact": booking_contact,
    }


def _deduplicate_by_distance(results: list[dict], limit: int) -> list[dict]:
    """Sort by distance, deduplicate by name, return top N results."""
    seen: set[str] = set()
    deduped: list[dict] = []
    for r in sorted(results, key=lambda x: x["distance_km"]):
        if r["name"] not in seen:
            seen.add(r["name"])
            deduped.append(r)
        if len(deduped) >= limit:
            break
    return deduped


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def search_nearby_healthcare(
    latitude: float,
    longitude: float,
    radius_m: int = 10000,
    limit: int = 8,
    specialty: str = "",
) -> list[dict]:
    """Search for healthcare facilities (doctors, clinics, hospitals) near
    the given coordinates using the Overpass API.

    When a specialty is provided (e.g. 'dentist', 'pharmacy'), the query
    targets that OSM amenity tag directly for more precise results.  Falls
    back to a broad healthcare query for unrecognised specialties.

    If the first query returns no results, it automatically retries with 1.5x
    the radius before giving up.

    Args:
        latitude:  User's latitude in decimal degrees.
        longitude: User's longitude in decimal degrees.
        radius_m:  Search radius in metres (default 10 km).
        limit:     Maximum number of results to return.
        specialty: Optional user-facing specialty string used to target the
                   Overpass query (e.g. 'dentist', 'cardiologist').

    Returns:
        List of facility dicts sorted by distance, or empty list on failure.
    """

    def _build_query(r: int) -> str:
        # Determine which OSM tags to query based on specialty hint
        specialty_lower = specialty.lower() if specialty else ""
        targeted_tags: list[str] = []
        for keyword, osm_tags in SPECIALTY_OSM_TAGS.items():
            if keyword in specialty_lower:
                targeted_tags = osm_tags
                break

        if targeted_tags:
            # Targeted query: only fetch the matched OSM amenity types
            tag_regex = "^(" + "|".join(targeted_tags) + ")$"
            lines = [
                f"[out:json][timeout:{REQUEST_TIMEOUT}];",
                "(",
                f'  node["amenity"~"{tag_regex}",i](around:{r},{latitude},{longitude});',
                f'  way["amenity"~"{tag_regex}",i](around:{r},{latitude},{longitude});',
                ");",
                "out center;",
            ]
        else:
            # Broad fallback: all healthcare facility types
            amenity_pat = (
                "^(doctors|clinic|hospital|health_post|nursing_home|"
                "dentist|pharmacy|dispensary|medical_centre|health_centre|"
                "health_facility|healthcare_centre)$"
            )
            lines = [
                f"[out:json][timeout:{REQUEST_TIMEOUT}];",
                "(",
                f'  node["amenity"~"{amenity_pat}",i](around:{r},{latitude},{longitude});',
                f'  way["amenity"~"{amenity_pat}",i](around:{r},{latitude},{longitude});',
                f'  node["healthcare"](around:{r},{latitude},{longitude});',
                f'  way["healthcare"](around:{r},{latitude},{longitude});',
                ");",
                "out center;",
            ]
        return "\n".join(lines)

    logger.info(
        "OSM: search_nearby_healthcare — lat=%.4f, lon=%.4f, radius=%dm",
        latitude,
        longitude,
        radius_m,
    )

    async def _fetch(r: int, query_override: str = "") -> list[dict]:
        """Try each Overpass endpoint in order, stop on first success."""
        query = query_override or _build_query(r)
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    resp = await client.post(endpoint, data={"data": query})
                    resp.raise_for_status()
                    data = resp.json()
                results = []
                for el in data.get("elements", []):
                    parsed = _parse_element(el, latitude, longitude)
                    if parsed:
                        results.append(parsed)
                logger.info(
                    "OSM: search_nearby_healthcare — %d raw results at radius=%dm via %s",
                    len(results),
                    r,
                    endpoint,
                )
                return results
            except Exception as exc:
                logger.warning(
                    "OSM: endpoint %s failed — %s. Trying next...", endpoint, exc
                )
        logger.error("OSM: all endpoints failed for radius=%dm", r)
        return []

    results = await _fetch(radius_m)

    # Auto-retry 1: larger radius (same targeted query)
    if not results:
        retry_radius = int(radius_m * 1.5)
        logger.info("OSM: no results at %dm — retrying at %dm", radius_m, retry_radius)
        results = await _fetch(retry_radius)

    # Auto-retry 2: if specialty was targeted and still nothing, fall back to broad query
    # (handles sparse OSM tagging in developing countries where amenity=dentist is rare)
    if not results and specialty:
        logger.info(
            "OSM: specialty-targeted search empty — falling back to broad healthcare query"
        )
        # Build broad query using the same radius
        amenity_pat = (
            "^(doctors|clinic|hospital|health_post|nursing_home|"
            "dentist|pharmacy|dispensary|medical_centre|health_centre|"
            "health_facility|healthcare_centre)$"
        )
        broad_query = "\n".join(
            [
                f"[out:json][timeout:{REQUEST_TIMEOUT}];",
                "(",
                f'  node["amenity"~"{amenity_pat}",i](around:{radius_m},{latitude},{longitude});',
                f'  way["amenity"~"{amenity_pat}",i](around:{radius_m},{latitude},{longitude});',
                f'  node["healthcare"](around:{radius_m},{latitude},{longitude});',
                f'  way["healthcare"](around:{radius_m},{latitude},{longitude});',
                ");",
                "out center;",
            ]
        )
        results = await _fetch(radius_m, query_override=broad_query)

    return _deduplicate_by_distance(results, limit)


async def search_nearby_emergency_services(
    latitude: float,
    longitude: float,
    radius_m: int = 10000,
    limit: int = 3,
) -> list[dict]:
    """Search for ambulance stations and hospitals near the given coordinates.

    Queries ambulance_station nodes first, then falls back to any hospital
    within the radius so there is always something to surface.

    Args:
        latitude:  User's latitude in decimal degrees.
        longitude: User's longitude in decimal degrees.
        radius_m:  Search radius in metres (default 10 km).
        limit:     Maximum number of results to return.

    Returns:
        List of facility dicts sorted by distance, or empty list on failure.
    """
    query = (
        f"[out:json][timeout:{REQUEST_TIMEOUT}];\n"
        "(\n"
        f'  node["emergency"="ambulance_station"]["name"](around:{radius_m},{latitude},{longitude});\n'
        f'  way["emergency"="ambulance_station"]["name"](around:{radius_m},{latitude},{longitude});\n'
        f'  node["amenity"="hospital"]["name"](around:{radius_m},{latitude},{longitude});\n'
        f'  way["amenity"="hospital"]["name"](around:{radius_m},{latitude},{longitude});\n'
        ");\n"
        "out center;"
    )
    logger.info(
        "OSM: search_nearby_emergency_services — lat=%.4f, lon=%.4f, radius=%dm",
        latitude,
        longitude,
        radius_m,
    )

    # Also apply endpoint rotation to emergency services query
    async def _fetch_emergency(query: str) -> list[dict]:
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    resp = await client.post(endpoint, data={"data": query})
                    resp.raise_for_status()
                    return resp.json().get("elements", [])
            except Exception as exc:
                logger.warning(
                    "OSM: emergency endpoint %s failed — %s. Trying next...",
                    endpoint,
                    exc,
                )
        return []

    elements = await _fetch_emergency(query)

    results = []
    for el in elements:
        parsed = _parse_element(el, latitude, longitude)
        if parsed:
            results.append(parsed)

    logger.info("OSM: search_nearby_emergency_services — %d raw results", len(results))
    return _deduplicate_by_distance(results, limit)


def get_emergency_number(country_code: Optional[str]) -> str:
    """Return the local emergency phone number for a given ISO 3166-1 alpha-2
    country code (e.g. 'US', 'GB', 'GH').

    Falls back to '112' (international standard) for unknown country codes.
    """
    if not country_code:
        return EMERGENCY_NUMBERS["DEFAULT"]
    return EMERGENCY_NUMBERS.get(country_code.upper(), EMERGENCY_NUMBERS["DEFAULT"])
