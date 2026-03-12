"""Ambulance search service"""

import logging

logger = logging.getLogger(__name__)


class AmbulanceSearchService:
    """Service for searching and locating ambulances"""

    @staticmethod
    async def find_nearest_ambulance(latitude: float, longitude: float) -> dict:
        """Find nearest available ambulance"""
        logger.info(
            "find_nearest_ambulance called — lat: %s, lon: %s", latitude, longitude
        )
        # TODO: Implement ambulance search logic
        pass

    @staticmethod
    async def search_by_location(location: str) -> list:
        """Search ambulances by location"""
        logger.info("search_by_location called — location: %s", location)
        # TODO: Implement location-based search
        pass
