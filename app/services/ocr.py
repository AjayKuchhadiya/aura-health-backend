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
You are a medical data extraction assistant.
Analyse the attached health document (prescription, lab report, or medical record)
and extract ALL structured medical information.

Return ONLY valid JSON with this exact schema — no markdown fences, no prose:
{
  "medications": [
    {
      "name": "string",
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
      "value": "string",
      "unit": "string or null",
      "reference_range": "string or null",
      "flag": "normal|high|low|null"
    }
  ],
  "doctor_name": "string or null",
  "clinic_name": "string or null",
  "document_date": "YYYY-MM-DD or null",
  "notes": "string or null"
}

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
