"""
Medical data extraction using Gemini 2.5 Flash multimodal (free tier).

Instead of an external OCR service, we pass image/PDF bytes directly to
Gemini and ask it to return structured JSON — no extra API costs.
"""

import base64
import json
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

_EXTRACTION_PROMPT = """
You are a medical data extraction assistant specialising in Indian healthcare documents.
Analyse the attached health document (prescription, lab report, or medical record)
and extract ALL structured medical information.

Return ONLY valid JSON with this exact schema — no markdown fences, no prose:
{
  "document_title": "string — a short, descriptive title for this document in plain English (e.g. 'Blood Count (CBC) Report', 'Diabetes & Thyroid Panel', 'Prescription — Hypertension', 'Lipid Profile Report', 'Discharge Summary'). Max 60 characters.",
  "medications": [
    {
      "name": "string (brand name exactly as written, e.g. 'Glycomet SR 500', 'Thyronorm 50')",
      "generic_name": "string or null (WHO INN generic name, e.g. 'Metformin' for Glycomet, 'Levothyroxine' for Thyronorm, 'Aspirin' for Ecosprin, 'Atorvastatin' for Atorva, 'Telmisartan' for Telma, 'Pantoprazole' for Pantop)",
      "dosage": "string",
      "frequency": "string",
      "duration": "string or null",
      "instructions": "string or null"
    }
  ],
  "diagnoses": ["string"],
  "lab_results": [
    {
      "test_name": "string",
      "value": "number (numeric value only, no units — e.g. 6.5 not '6.5%')",
      "unit": "string or null (e.g. '%', 'mg/dL', 'g/dL', 'μIU/mL', 'ng/mL', 'pg/mL', 'mm/hr')",
      "reference_range": "string or null (e.g. '4.0-5.6%', '70-100 mg/dL', '11.5-16.5 g/dL')",
      "flag": "normal|high|low|null",
      "date_taken": "YYYY-MM-DD or null (use the document date if no per-test date is shown)"
    }
  ],
  "doctor_name": "string or null",
  "clinic_name": "string or null",
  "document_date": "YYYY-MM-DD or null",
  "notes": "string or null"
}

IMPORTANT CONTEXT — This document is from an INDIAN healthcare provider:

Medications:
- Drug names will often be Indian brand names. Always populate generic_name using the INN.
  Common Indian brand → generic mappings (not exhaustive):
  Glycomet/Glucophage → Metformin | Thyronorm/Eltroxin → Levothyroxine
  Ecosprin → Aspirin | Atorva/Storvas/Lipitor → Atorvastatin
  Telma/Telmikind → Telmisartan | Amlokind/Amlodac → Amlodipine
  Pantop/Pan/Nexpro → Pantoprazole | Omez/Omeprazole → Omeprazole
  Glycomet GP → Metformin + Glipizide | Janumet → Sitagliptin + Metformin
  Arkamin/Catapres → Clonidine | Deplatt/Clopivas → Clopidogrel
  Forxiga → Dapagliflozin | Jardiance → Empagliflozin | Galvus → Vildagliptin
  Shelcal/Calcirol → Calcium + Vitamin D3 | Becosules → B-complex vitamins

Lab results:
- Standard Indian units: mg/dL for glucose and cholesterol (NOT mmol/L), g/dL for haemoglobin,
  μIU/mL or mIU/L for TSH, ng/mL for Vitamin D (25-OH), pg/mL for Vitamin B12,
  mg/L for CRP/hsCRP, mm/hr for ESR, U/L for liver enzymes (SGOT/SGPT/ALP).
- Common Indian lab abbreviations to recognise:
  Hb/Haemoglobin | TLC (Total Leucocyte Count) | DLC (Differential Leucocyte Count)
  ESR | FBS/FBG (Fasting Blood Sugar/Glucose) | PPBS/PLBS (Post Prandial Blood Sugar)
  RBS (Random Blood Sugar) | HbA1c (Glycated Haemoglobin)
  Sr./S. prefix = Serum (e.g. Sr. Creatinine = Serum Creatinine)
  KFT/RFT (Kidney/Renal Function Test) | LFT (Liver Function Test)
  SGOT (= AST) | SGPT (= ALT) | ALP | T.Bil (Total Bilirubin) | D.Bil (Direct Bilirubin)
  BUN (Blood Urea Nitrogen) | S. Uric Acid | T3 | T4 | TSH
  25-OH Vit D / Vitamin D Total | Vit B12 / Cobalamin | S. Ferritin | TIBC | PT/INR | aPTT
  eGFR | Urine R/E or Urine Routine & Microscopy | Urine ACR (Albumin:Creatinine Ratio)
- When a test appears as part of a panel (e.g. Lipid Profile, LFT, KFT, CBC), extract each
  individual parameter as a separate lab_result row.

Common Indian diagnoses to recognise:
  Type 2 Diabetes Mellitus (T2DM) | Hypothyroidism | Hypertension (HTN)
  Coronary Artery Disease (CAD) | Chronic Kidney Disease (CKD) | PCOS
  Iron Deficiency Anaemia | Vitamin D Deficiency | Vitamin B12 Deficiency
  Dyslipidaemia | Non-Alcoholic Fatty Liver Disease (NAFLD) | Gout | Osteoporosis

IMPORTANT for lab_results:
- value MUST be a JSON number (float), not a string. If the value cannot be parsed as a number, omit that result.
- Extract every individual test row — do not summarise or combine tests.
- Use the document_date as date_taken if no per-test date is present.

If a field has no data, use null or an empty list [].
Do not guess or hallucinate — only extract what is clearly visible in the document.
"""


async def extract_medical_data(file_bytes: bytes, mime_type: str) -> dict:
    """
    Pass file bytes to Gemini 2.5 Flash for multimodal medical data extraction.

    Args:
        file_bytes:  Raw bytes of the uploaded file (image or PDF).
        mime_type:   MIME type string, e.g. 'image/jpeg' or 'application/pdf'.

    Returns:
        Parsed dict matching the schema above, or {"error": "..."} on failure.
    """
    if not settings.GEMINI_API_KEY:
        return {"error": "GEMINI_API_KEY is not configured."}

    try:
        from google import genai
        from google.genai import types as genai_types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        # For PDF, Gemini expects inline_data with base64; for images, same approach
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                genai_types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                _EXTRACTION_PROMPT,
            ],
        )

        raw_text = response.text.strip()

        # Strip markdown fences if the model wrapped the JSON anyway
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        extracted = json.loads(raw_text)
        logger.info(
            "Gemini extraction complete — medications: %d, diagnoses: %d",
            len(extracted.get("medications", [])),
            len(extracted.get("diagnoses", [])),
        )
        return extracted

    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON response: %s", exc)
        return {"error": f"Could not parse Gemini response as JSON: {exc}"}
    except Exception as exc:
        logger.exception("Gemini extraction failed")
        return {"error": f"Extraction failed: {exc}"}
