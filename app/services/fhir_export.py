"""
FHIR R4 export service.

Maps a user's Aura "Digital Twin" data to standard FHIR R4 resources and
wraps them in a FHIR Bundle for interoperable data export.

Resources produced:
  - Patient          ← User profile + medical_profile JSONB
  - MedicationStatement ← Each Medication row (FHIR R4; deprecated in R5)
  - Observation      ← Each LabResult row

All drug codes use RxNorm (standard in India-compatible systems) where
available, with a fallback to a plain text display name.
Lab results use LOINC codes for the most common Indian panel tests.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LOINC code map for common Indian lab tests
# Covers CBC, LFT, KFT, Lipid Profile, thyroid, vitamins, diabetes markers
# ---------------------------------------------------------------------------
_LOINC_MAP: dict[str, tuple[str, str]] = {
    # Diabetes
    "hba1c":                    ("4548-4",  "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "fbs":                      ("1558-6",  "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "fasting blood sugar":      ("1558-6",  "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "fasting blood glucose":    ("1558-6",  "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "fbg":                      ("1558-6",  "Fasting glucose [Mass/volume] in Serum or Plasma"),
    "ppbs":                     ("1521-4",  "Glucose [Mass/volume] in Serum or Plasma --2 hours post meal"),
    "rbs":                      ("2345-7",  "Glucose [Mass/volume] in Serum or Plasma"),
    "random blood sugar":       ("2345-7",  "Glucose [Mass/volume] in Serum or Plasma"),
    # Thyroid
    "tsh":                      ("3016-3",  "Thyrotropin [Units/volume] in Serum or Plasma"),
    "t3":                       ("3053-6",  "Triiodothyronine (T3) [Mass/volume] in Serum or Plasma"),
    "t4":                       ("3026-2",  "Thyroxine (T4) [Mass/volume] in Serum or Plasma"),
    "free t3":                  ("14928-0", "Triiodothyronine (T3) Free [Mass/volume] in Serum or Plasma"),
    "free t4":                  ("14920-7", "Thyroxine (T4) free [Mass/volume] in Serum or Plasma"),
    # CBC
    "haemoglobin":              ("718-7",   "Hemoglobin [Mass/volume] in Blood"),
    "hemoglobin":               ("718-7",   "Hemoglobin [Mass/volume] in Blood"),
    "hb":                       ("718-7",   "Hemoglobin [Mass/volume] in Blood"),
    "tlc":                      ("6690-2",  "Leukocytes [#/volume] in Blood by Automated count"),
    "total leucocyte count":    ("6690-2",  "Leukocytes [#/volume] in Blood by Automated count"),
    "wbc":                      ("6690-2",  "Leukocytes [#/volume] in Blood by Automated count"),
    "platelet count":           ("777-3",   "Platelets [#/volume] in Blood by Automated count"),
    "platelets":                ("777-3",   "Platelets [#/volume] in Blood by Automated count"),
    "hematocrit":               ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "pcv":                      ("20570-8", "Hematocrit [Volume Fraction] of Blood"),
    "esr":                      ("30341-2", "Erythrocyte sedimentation rate"),
    # Kidney (KFT / RFT)
    "serum creatinine":         ("2160-0",  "Creatinine [Mass/volume] in Serum or Plasma"),
    "sr. creatinine":           ("2160-0",  "Creatinine [Mass/volume] in Serum or Plasma"),
    "s. creatinine":            ("2160-0",  "Creatinine [Mass/volume] in Serum or Plasma"),
    "creatinine":               ("2160-0",  "Creatinine [Mass/volume] in Serum or Plasma"),
    "bun":                      ("3094-0",  "Urea nitrogen [Mass/volume] in Serum or Plasma"),
    "blood urea":               ("3094-0",  "Urea nitrogen [Mass/volume] in Serum or Plasma"),
    "uric acid":                ("3084-1",  "Urate [Mass/volume] in Serum or Plasma"),
    "s. uric acid":             ("3084-1",  "Urate [Mass/volume] in Serum or Plasma"),
    "egfr":                     ("62238-1", "Glomerular filtration rate/1.73 sq M.predicted"),
    "urine acr":                ("9318-7",  "Albumin/Creatinine [Mass Ratio] in Urine"),
    # Liver (LFT)
    "sgpt":                     ("1742-6",  "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "alt":                      ("1742-6",  "Alanine aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "sgot":                     ("1920-8",  "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "ast":                      ("1920-8",  "Aspartate aminotransferase [Enzymatic activity/volume] in Serum or Plasma"),
    "alp":                      ("6768-6",  "Alkaline phosphatase [Enzymatic activity/volume] in Serum or Plasma"),
    "total bilirubin":          ("1975-2",  "Bilirubin.total [Mass/volume] in Serum or Plasma"),
    "t. bilirubin":             ("1975-2",  "Bilirubin.total [Mass/volume] in Serum or Plasma"),
    "direct bilirubin":         ("1968-7",  "Bilirubin.direct [Mass/volume] in Serum or Plasma"),
    "d. bilirubin":             ("1968-7",  "Bilirubin.direct [Mass/volume] in Serum or Plasma"),
    "total protein":            ("2885-2",  "Protein [Mass/volume] in Serum or Plasma"),
    "albumin":                  ("1751-7",  "Albumin [Mass/volume] in Serum or Plasma"),
    # Lipid profile
    "total cholesterol":        ("2093-3",  "Cholesterol [Mass/volume] in Serum or Plasma"),
    "cholesterol":              ("2093-3",  "Cholesterol [Mass/volume] in Serum or Plasma"),
    "hdl":                      ("2085-9",  "Cholesterol in HDL [Mass/volume] in Serum or Plasma"),
    "hdl cholesterol":          ("2085-9",  "Cholesterol in HDL [Mass/volume] in Serum or Plasma"),
    "ldl":                      ("2089-1",  "Cholesterol in LDL [Mass/volume] in Serum or Plasma"),
    "ldl cholesterol":          ("2089-1",  "Cholesterol in LDL [Mass/volume] in Serum or Plasma"),
    "triglycerides":            ("2571-8",  "Triglyceride [Mass/volume] in Serum or Plasma"),
    "vldl":                     ("13458-5", "Cholesterol in VLDL [Mass/volume] in Serum or Plasma"),
    # Vitamins & minerals
    "vitamin d":                ("1989-3",  "25-hydroxyvitamin D3 [Mass/volume] in Serum or Plasma"),
    "25-oh vitamin d":          ("1989-3",  "25-hydroxyvitamin D3 [Mass/volume] in Serum or Plasma"),
    "vitamin d total":          ("62292-8", "25-hydroxyvitamin D2+D3 [Mass/volume] in Serum or Plasma"),
    "vitamin b12":              ("2132-9",  "Cobalamin (Vitamin B12) [Mass/volume] in Serum or Plasma"),
    "vit b12":                  ("2132-9",  "Cobalamin (Vitamin B12) [Mass/volume] in Serum or Plasma"),
    "cobalamin":                ("2132-9",  "Cobalamin (Vitamin B12) [Mass/volume] in Serum or Plasma"),
    "serum ferritin":           ("2276-4",  "Ferritin [Mass/volume] in Serum or Plasma"),
    "ferritin":                 ("2276-4",  "Ferritin [Mass/volume] in Serum or Plasma"),
    "tibc":                     ("2501-5",  "Iron binding capacity [Mass/volume] in Serum or Plasma"),
    # Coagulation
    "pt":                       ("5902-2",  "Prothrombin time (PT)"),
    "inr":                      ("6301-6",  "INR in Platelet poor plasma by Coagulation assay"),
    "aptt":                     ("3173-2",  "aPTT in Blood by Coagulation assay"),
}


def _loinc_for(test_name: str) -> Optional[tuple[str, str]]:
    """Return (loinc_code, display) for a test name, or None if not mapped."""
    return _LOINC_MAP.get(test_name.lower().strip())


# ---------------------------------------------------------------------------
# Resource builders
# ---------------------------------------------------------------------------

def _build_patient(user: Any, profile: dict) -> dict:
    """Map a User row + medical_profile JSONB to a FHIR R4 Patient resource."""
    mh: dict = profile.get("medical_history", {})
    loc: dict = profile.get("location", {})
    dob: Optional[str] = profile.get("date_of_birth") or None

    resource: dict = {
        "resourceType": "Patient",
        "id": f"patient-{user.id}",
        "meta": {
            "profile": ["http://hl7.org/fhir/StructureDefinition/Patient"],
        },
        "identifier": [
            {
                "system": "urn:aura-health:user-id",
                "value": str(user.id),
            }
        ],
        "active": user.is_active,
        "name": [
            {
                "use": "official",
                "text": user.username or user.email,
            }
        ],
        "telecom": [
            {"system": "email", "value": user.email, "use": "home"}
        ],
    }

    if dob:
        resource["birthDate"] = dob

    # Address from profile location (India)
    address_parts: dict = {}
    if loc.get("city"):
        address_parts["city"] = loc["city"]
    if loc.get("state"):
        address_parts["state"] = loc["state"]
    if loc.get("postal_code"):
        address_parts["postalCode"] = loc["postal_code"]
    if address_parts:
        address_parts["country"] = loc.get("country", "India")
        address_parts["use"] = "home"
        resource["address"] = [address_parts]

    # Allergies as extension (FHIR AllergyIntolerance would be a separate resource;
    # we embed them as a simple extension for portability in the bundle)
    allergies: list = mh.get("allergies", [])
    if allergies:
        resource.setdefault("extension", []).append({
            "url": "urn:aura-health:allergies",
            "valueString": ", ".join(allergies),
        })

    # Blood type extension
    blood_type = mh.get("blood_type")
    if blood_type:
        resource.setdefault("extension", []).append({
            "url": "urn:aura-health:blood-type",
            "valueString": blood_type,
        })

    # Chronic conditions as extension
    conditions: list = mh.get("chronic_conditions", [])
    if conditions:
        resource.setdefault("extension", []).append({
            "url": "urn:aura-health:chronic-conditions",
            "valueString": ", ".join(conditions),
        })

    return resource


def _build_medication_statement(med: Any, patient_ref: str) -> dict:
    """Map a Medication row to a FHIR R4 MedicationStatement resource."""
    status = "active"
    if med.end_date and med.end_date < date.today():
        status = "completed"

    resource: dict = {
        "resourceType": "MedicationStatement",
        "id": f"medstmt-{med.id}",
        "status": status,
        "medicationCodeableConcept": {
            "coding": [
                {
                    "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                    "display": med.medication_name,
                }
            ],
            "text": med.medication_name,
        },
        "subject": {"reference": patient_ref},
        "effectivePeriod": {
            "start": med.start_date.isoformat(),
        },
        "dosage": [
            {
                "text": f"{med.dosage} — {med.frequency}",
                "timing": {
                    "repeat": {
                        "frequency": 1,
                        "period": 1,
                        "periodUnit": "d",
                    }
                },
            }
        ],
    }

    if med.end_date:
        resource["effectivePeriod"]["end"] = med.end_date.isoformat()

    if med.notes:
        resource["note"] = [{"text": med.notes}]

    return resource


def _build_observation(lab: Any, patient_ref: str) -> dict:
    """Map a LabResult row to a FHIR R4 Observation resource."""
    loinc = _loinc_for(lab.test_name)

    coding: list[dict] = []
    if loinc:
        coding.append({
            "system": "http://loinc.org",
            "code": loinc[0],
            "display": loinc[1],
        })
    # Always include display text regardless of LOINC availability
    coding.append({
        "system": "urn:aura-health:lab-test",
        "display": lab.test_name,
    })

    # Map flag to FHIR interpretation code
    interp_map = {
        "high": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "H", "display": "High"}],
        "low":  [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "L", "display": "Low"}],
        "normal": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation", "code": "N", "display": "Normal"}],
    }

    resource: dict = {
        "resourceType": "Observation",
        "id": f"obs-{lab.id}",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": {
            "coding": coding,
            "text": lab.test_name,
        },
        "subject": {"reference": patient_ref},
        "valueQuantity": {
            "value": lab.value,
            "unit": lab.unit or "",
            "system": "http://unitsofmeasure.org",
            "code": lab.unit or "",
        },
    }

    if lab.date_taken:
        resource["effectiveDateTime"] = lab.date_taken.isoformat()

    if lab.flag and lab.flag in interp_map:
        resource["interpretation"] = [{"coding": interp_map[lab.flag]}]

    if lab.reference_range:
        resource["referenceRange"] = [{"text": lab.reference_range}]

    return resource


# ---------------------------------------------------------------------------
# Public builder — full FHIR Bundle
# ---------------------------------------------------------------------------

def build_fhir_bundle(
    user: Any,
    medications: list[Any],
    lab_results: list[Any],
) -> dict:
    """
    Build a FHIR R4 'document' Bundle containing:
      - 1 Patient resource
      - N MedicationStatement resources
      - M Observation resources (lab results)

    Returns a plain dict ready to be serialised as JSON.
    """
    bundle_id = str(uuid.uuid4())
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    profile: dict = user.medical_profile or {}
    patient_resource = _build_patient(user, profile)
    patient_ref = f"Patient/patient-{user.id}"

    entries: list[dict] = [
        {
            "fullUrl": f"urn:uuid:patient-{user.id}",
            "resource": patient_resource,
        }
    ]

    for med in medications:
        try:
            entries.append({
                "fullUrl": f"urn:uuid:medstmt-{med.id}",
                "resource": _build_medication_statement(med, patient_ref),
            })
        except Exception:
            logger.exception("Failed to build MedicationStatement for med_id=%s", med.id)

    for lab in lab_results:
        try:
            entries.append({
                "fullUrl": f"urn:uuid:obs-{lab.id}",
                "resource": _build_observation(lab, patient_ref),
            })
        except Exception:
            logger.exception("Failed to build Observation for lab_id=%s", lab.id)

    bundle = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {
            "lastUpdated": timestamp,
            "profile": ["http://hl7.org/fhir/StructureDefinition/Bundle"],
        },
        "type": "document",
        "timestamp": timestamp,
        "entry": entries,
    }

    logger.info(
        "FHIR Bundle built — user_id=%s, entries=%d (1 Patient, %d MedStmt, %d Obs)",
        user.id, len(entries), len(medications), len(lab_results),
    )
    return bundle
