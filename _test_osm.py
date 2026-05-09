import asyncio
from app.services.osm import search_nearby_healthcare, SPECIALTY_OSM_TAGS


async def test():
    # Test keyword extraction
    for kw in ["tooth cavity", "dentist", "teeth", "general practitioner", "eye"]:
        kw_lower = kw.lower()
        matched = next(
            (osm for k, osm in SPECIALTY_OSM_TAGS.items() if k in kw_lower), None
        )
        print(f"  '{kw}' -> OSM tags: {matched}")

    print()
    print("=== Dentist search (targeted) ===")
    results = await search_nearby_healthcare(
        27.1767, 78.0081, radius_m=10000, limit=5, specialty="dentist"
    )
    print(f"  Found: {len(results)}")

    print()
    print("=== Broad fallback search ===")
    results2 = await search_nearby_healthcare(
        27.1767, 78.0081, radius_m=10000, limit=5, specialty=""
    )
    print(f"  Found: {len(results2)}")
    for r in results2[:3]:
        print(f"  - {r['name']} | {r['booking_contact']}")
        print(f"    Maps: {r['maps_link']}")


asyncio.run(test())
