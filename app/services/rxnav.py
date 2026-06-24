"""
Drug-Drug Interaction checking via the US NLM RxNav REST API.
100% free, no API key required.

Workflow for Indian users:
1. Normalize every drug name to its WHO INN generic name via Gemini
   (Indian brand names like "Glycomet", "Thyronorm", "Ecosprin" are not in
   the RxNorm database — only their generic equivalents are).
2. Resolve each INN to an RxCUI (RxNorm Concept Unique Identifier) via RxNav.
3. Query the RxNav Interaction API with all RxCUIs at once.
4. If interactions are found, use Gemini to translate the clinical warning into
   simple, empathetic language appropriate for an Indian patient.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

_RXNAV_BASE = "https://rxnav.nlm.nih.gov/REST"

# Timeout for RxNav API calls (free public API — be generous)
_HTTP_TIMEOUT = 10.0


# ---------------------------------------------------------------------------
# Step 1 — Normalise Indian brand/combination names to WHO INN generic names
# ---------------------------------------------------------------------------

async def _normalize_to_generic(drug_name: str) -> str:
    """
    Use Gemini to map any drug name (including Indian brand names) to its
    WHO INN generic name(s). Returns the original name on failure so the
    workflow degrades gracefully.
    """
    if not settings.GEMINI_API_KEY:
        return drug_name

    prompt = (
        f'The drug name is "{drug_name}". It may be an Indian brand name '
        f"(e.g. Glycomet = Metformin, Thyronorm = Levothyroxine, Ecosprin = Aspirin, "
        f"Telma = Telmisartan, Atorva = Atorvastatin, Deplatt = Clopidogrel, "
        f"Forxiga = Dapagliflozin, Jardiance = Empagliflozin, Galvus = Vildagliptin, "
        f"Pantop = Pantoprazole, Amlokind = Amlodipine). "
        f"Return ONLY the WHO International Nonproprietary Name (INN) generic name(s) "
        f"of the active ingredient(s) in lowercase, comma-separated if a combination. "
        f"No explanations, no brand names, no dosage — just the INN name(s)."
    )

    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        generic = response.text.strip().lower()
        logger.info("Generic name resolved: '%s' → '%s'", drug_name, generic)
        return generic
    except Exception as exc:
        logger.warning("Could not normalise drug name '%s': %s", drug_name, exc)
        return drug_name.lower()


# ---------------------------------------------------------------------------
# Step 2 — Resolve INN generic name to RxCUI
# ---------------------------------------------------------------------------

async def _get_rxcui(generic_name: str) -> Optional[str]:
    """
    Query RxNav to get the RxCUI for a generic drug name.
    Returns None if the drug is not found in RxNorm.
    """
    # Handle combination drugs — take the first active ingredient for lookup
    # (RxNav interaction API also accepts individual RxCUIs for multi-ingredient drugs)
    primary_name = generic_name.split(",")[0].strip()

    url = f"{_RXNAV_BASE}/rxcui.json"
    params = {"name": primary_name, "search": "1"}  # search=1 enables approximate matching

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        rxcui = (
            data.get("idGroup", {})
            .get("rxnormId", [None])[0]
        )
        if rxcui:
            logger.info("RxCUI resolved: '%s' → %s", primary_name, rxcui)
        else:
            logger.info("No RxCUI found for '%s'", primary_name)
        return rxcui

    except Exception as exc:
        logger.warning("RxNav RxCUI lookup failed for '%s': %s", primary_name, exc)
        return None


# ---------------------------------------------------------------------------
# Step 3 — Query RxNav interaction API
# ---------------------------------------------------------------------------

async def _fetch_interactions(rxcuis: list[str]) -> list[dict]:
    """
    Query the RxNav interaction list endpoint with multiple RxCUIs.
    Returns a flat list of interaction dicts, each with description and severity.
    """
    if len(rxcuis) < 2:
        return []

    url = f"{_RXNAV_BASE}/interaction/list.json"
    params = {"rxcuis": " ".join(rxcuis)}

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        interactions = []
        full_interaction_type_group = data.get("fullInteractionTypeGroup", [])
        for group in full_interaction_type_group:
            for interaction_type in group.get("fullInteractionType", []):
                for pair in interaction_type.get("interactionPair", []):
                    drug_1 = pair.get("interactionConcept", [{}])[0]
                    drug_2 = pair.get("interactionConcept", [{}])[1] if len(pair.get("interactionConcept", [])) > 1 else {}
                    interactions.append({
                        "drug_1": drug_1.get("minConceptItem", {}).get("name", "Unknown"),
                        "drug_2": drug_2.get("minConceptItem", {}).get("name", "Unknown"),
                        "severity": pair.get("severity", "unknown"),
                        "description": pair.get("description", ""),
                        "source": group.get("sourceDisclaimer", ""),
                    })

        logger.info("RxNav returned %d interaction(s) for RxCUIs: %s", len(interactions), rxcuis)
        return interactions

    except Exception as exc:
        logger.warning("RxNav interaction fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Step 4 — Translate clinical warning to patient-friendly language (India)
# ---------------------------------------------------------------------------

async def _translate_warning_for_patient(
    new_drug: str,
    interactions: list[dict],
) -> str:
    """
    Use Gemini to translate clinical drug interaction data into simple,
    empathetic language appropriate for an Indian patient.
    """
    if not settings.GEMINI_API_KEY:
        # Fallback: plain-text summary without AI translation
        summaries = [
            f"{i['drug_1']} + {i['drug_2']}: {i['description']}"
            for i in interactions
        ]
        return (
            f"Possible drug interaction detected with {new_drug}. "
            "Please consult your doctor before taking this medication. "
            + " | ".join(summaries)
        )

    interaction_text = "\n".join(
        f"- {i['drug_1']} with {i['drug_2']} (Severity: {i['severity']}): {i['description']}"
        for i in interactions
    )

    prompt = (
        f"You are a helpful health assistant. A patient in India has been prescribed "
        f"'{new_drug}' and a potential drug interaction has been detected with their "
        f"existing medications.\n\n"
        f"Clinical interaction data:\n{interaction_text}\n\n"
        f"Please translate this warning into simple, warm, and empathetic language "
        f"that an Indian patient can easily understand. Use clear, everyday Hindi-English "
        f"(Hinglish-friendly) phrasing if needed, but keep the response in English. "
        f"Advise them to consult their doctor (use the Indian term 'doctor sahab' or simply "
        f"'your doctor') before taking the new medication. Keep the response concise — "
        f"2-3 sentences maximum. Do NOT diagnose or say the interaction will definitely cause harm."
    )

    try:
        from google import genai

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as exc:
        logger.warning("Gemini translation of interaction warning failed: %s", exc)
        summaries = [i["description"] for i in interactions if i.get("description")]
        return (
            f"A possible interaction was found between {new_drug} and your existing medicines. "
            "Please consult your doctor before starting this medication. "
            + (" ".join(summaries[:2]) if summaries else "")
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def check_drug_interactions(
    new_drug: str,
    existing_drugs: list[str],
) -> dict:
    """
    Check for drug-drug interactions between a new medication and an existing regimen.

    Args:
        new_drug:       Name of the newly added medication (brand or generic).
        existing_drugs: List of current medication names (brand or generic).

    Returns:
        {
            "has_interaction": bool,
            "warning": str | None,        # patient-friendly AI-translated warning
            "interactions_found": int,    # raw count
        }
    """
    if not existing_drugs:
        return {"has_interaction": False, "warning": None, "interactions_found": 0}

    all_drugs = [new_drug] + existing_drugs

    # Step 1: Normalise all names to generics in parallel
    import asyncio
    generics = await asyncio.gather(*[_normalize_to_generic(d) for d in all_drugs])

    # Step 2: Resolve RxCUIs (skip drugs we can't resolve)
    rxcuis_raw = await asyncio.gather(*[_get_rxcui(g) for g in generics])
    rxcuis = [r for r in rxcuis_raw if r is not None]

    if len(rxcuis) < 2:
        logger.info(
            "Insufficient RxCUIs resolved (%d) — skipping interaction check", len(rxcuis)
        )
        return {"has_interaction": False, "warning": None, "interactions_found": 0}

    # Step 3: Fetch interactions
    interactions = await _fetch_interactions(rxcuis)

    if not interactions:
        return {"has_interaction": False, "warning": None, "interactions_found": 0}

    # Step 4: Translate to patient-friendly language
    warning = await _translate_warning_for_patient(new_drug, interactions)

    return {
        "has_interaction": True,
        "warning": warning,
        "interactions_found": len(interactions),
    }
