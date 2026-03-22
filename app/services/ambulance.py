"""Ambulance search service.

Currently returns realistic stub responses so the agent tools are
functional end-to-end while the real dispatch API integration is pending.

TODO: Replace stub responses with calls to a real ambulance dispatch API
(e.g. a proprietary fleet-management system or an emergency-services
webhook) once the integration contract is defined.
"""

import logging
import uuid
from math import radians, cos, sin, asin, sqrt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stub fleet data — replace with a real data source / API call
# ---------------------------------------------------------------------------
_STUB_FLEET = [
    {
        "unit_id": "AMB-001",
        "driver_name": "James Osei",
        "contact_number": "+1-800-AMB-0001",
        "latitude": 5.6037,
        "longitude": -0.1870,
        "status": "available",
    },
    {
        "unit_id": "AMB-002",
        "driver_name": "Akua Mensah",
        "contact_number": "+1-800-AMB-0002",
        "latitude": 5.6145,
        "longitude": -0.2057,
        "status": "available",
    },
    {
        "unit_id": "AMB-003",
        "driver_name": "Kofi Asante",
        "contact_number": "+1-800-AMB-0003",
        "latitude": 5.5913,
        "longitude": -0.2220,
        "status": "available",
    },
]


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two GPS points."""
    R = 6371.0  # Earth radius in km
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


class AmbulanceSearchService:
    """Service for searching and locating ambulances."""

    @staticmethod
    async def find_nearest_ambulance(latitude: float, longitude: float) -> dict:
        """Find the nearest available ambulance to the given GPS coordinates.

        Returns a dict with unit details and an estimated arrival time, or
        None if no units are available.
        """
        logger.info(
            "find_nearest_ambulance called — lat: %s, lon: %s", latitude, longitude
        )

        available = [u for u in _STUB_FLEET if u["status"] == "available"]
        if not available:
            logger.warning("find_nearest_ambulance — no units available")
            return None

        # Pick the unit with the shortest great-circle distance
        nearest = min(
            available,
            key=lambda u: _haversine_km(
                latitude, longitude, u["latitude"], u["longitude"]
            ),
        )
        distance_km = _haversine_km(
            latitude, longitude, nearest["latitude"], nearest["longitude"]
        )
        # Rough ETA: assume average speed of 40 km/h in urban areas
        eta_minutes = max(1, round((distance_km / 40.0) * 60))

        logger.info(
            "Nearest ambulance: %s — distance: %.2f km, ETA: %d min",
            nearest["unit_id"],
            distance_km,
            eta_minutes,
        )

        return {
            "unit_id": nearest["unit_id"],
            "driver_name": nearest["driver_name"],
            "contact_number": nearest["contact_number"],
            "distance_km": round(distance_km, 2),
            "estimated_arrival_minutes": eta_minutes,
            "status": "en_route",
            "note": (
                "⚠️ This is a platform dispatch. Please ALSO call your local emergency "
                "services (911 or equivalent) for the fastest response."
            ),
        }

    @staticmethod
    async def search_by_location(location: str) -> dict:
        """Dispatch an ambulance to a plain-language location description.

        Returns dispatch confirmation details, or None if dispatch fails.
        """
        logger.info("search_by_location called — location: %s", location)

        available = [u for u in _STUB_FLEET if u["status"] == "available"]
        if not available:
            logger.warning("search_by_location — no units available")
            return None

        # For a text-based request, assign the first available unit
        unit = available[0]
        request_id = str(uuid.uuid4())[:8].upper()

        logger.info(
            "Ambulance dispatched — request_id: %s, unit: %s, location: %s",
            request_id,
            unit["unit_id"],
            location,
        )

        return {
            "request_id": request_id,
            "unit_id": unit["unit_id"],
            "driver_name": unit["driver_name"],
            "contact_number": unit["contact_number"],
            "dispatched_to": location,
            "estimated_arrival_minutes": 10,
            "status": "dispatched",
            "note": (
                "⚠️ This is a platform dispatch. Please ALSO call your local emergency "
                "services (911 or equivalent) for the fastest response."
            ),
        }
