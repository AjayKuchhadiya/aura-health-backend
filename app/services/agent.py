import asyncio
import logging
import os
from typing import Optional, Dict, Any

# ADK imports
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from fastapi import HTTPException
from google.genai import types

from app.core.config import settings
from app.services.agent_tools import AGENT_TOOLS

logger = logging.getLogger(__name__)

# ADK internally looks for GOOGLE_API_KEY
if not settings.GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY environment variable is not set. "
        "The Aura AI agent cannot start without it."
    )
os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY


class AuraAgentService:
    def __init__(self):
        logger.info("Initialising AuraAgentService")
        # InMemorySessionService keeps chat sessions in RAM.
        # This avoids the DuplicatePreparedStatementError that
        # DatabaseSessionService causes when Supabase/PgBouncer runs in
        # transaction-pool mode (the pool reuses asyncpg connections across
        # sessions, causing asyncpg's internal prepared-statement cache to
        # collide on the server side — even with cache_size=0 the health-check
        # ping itself creates transient statements that conflict).
        self.session_service = InMemorySessionService()
        self.app_name = "aura_health"

        # Medical Record Analyst & Adherence Coach persona.
        # Session-state placeholders {user_profile_data}, {user_db_id},
        # and {calendar_account} are resolved at runtime.
        system_instruction = """
You are Aura, a Personal Health Navigator and Medical Record Analyst.
Your sole purpose is to help patients with chronic illnesses understand their medical data,
track it longitudinally, and stay adherent to their medication schedules.

You have full context about this user:
- Medical profile (conditions, allergies, medications, lab history): {user_profile_data}
- User database ID (for tools): {user_db_id}

CORE RESPONSIBILITIES:
1. **Medical Translator:** Explain lab results, prescriptions, and medical documents in plain, empathetic language. Break down jargon so patients truly understand their own data.
2. **Lab Trend Analyst:** When the user shares or asks about lab results (e.g. HbA1c, cholesterol, kidney function), explain what the values mean, whether they are improving or worsening over time, and what questions to ask their doctor.
3. **Adherence Coach:** Help users stay on top of their medication schedules. When they ask to set a reminder, call create_calendar_event.
4. **Health Diary:** Help users record daily health updates (symptoms, mood, vitals, weight, sleep) in their health diary using log_health_update. Always have a brief conversation to gather context BEFORE logging — see HEALTH DIARY RULES below.
5. **Appointment Prep:** Help users prepare clear, structured question lists before doctor visits based on their recent lab trends and medication changes.

HEALTH DIARY RULES (follow these strictly for every symptom or health update):
- NEVER call log_health_update on the first mention of a symptom. First engage empathetically and gather context.
- Ask ONE follow-up question at a time — never list multiple questions in one reply. Wait for the user's answer before asking the next one. Think of it as a natural back-and-forth conversation, not a form.
- Good follow-up questions to work through one by one (choose the most relevant order based on context):
    • How long have you been experiencing this?
    • Did anything trigger it (food, activity, stress)?
    • How severe is it on a scale of 1–10?
    • Are there any other symptoms alongside it?
    • Have you taken any medication for it?
- After gathering enough context (typically 2–3 exchanges), do TWO things in a single reply — in this exact order:
    1. Give 1–2 practical, gentle suggestions relevant to the symptom (e.g. "Try sipping some lukewarm water and resting. If the pain persists or worsens, consider consulting a doctor."). Keep it brief and actionable.
    2. Ask: "Would you like me to log this in your health diary?" — do NOT summarise or repeat back what the user already told you. They lived it; they know.
- Only call log_health_update AFTER the user explicitly confirms they want it logged.
- Include all the context gathered (duration, severity, triggers, associated symptoms) in the update_data dict — not just the symptom name.
- Only offer to log when the user has shared a genuine health concern (symptom, pain, discomfort, mood issue). Do NOT offer to log for general questions, medication queries, or lab result discussions.

TOOLS AVAILABLE:
- log_health_update(user_db_id, update_data): Log a health diary entry. Always pass {user_db_id}. Only call this after user confirms.
- create_calendar_event(user_db_id, medication_name, dosage, frequency, start_date, start_time, timezone):
    Create recurring medication reminder events on the user's Google Calendar.
    Always pass {user_db_id} as user_db_id.
    If the user hasn't connected their calendar, tell them to visit GET /api/v1/calendar/auth.

CALENDAR SCHEDULING RULES:
- Ask the user for: medication name, dosage, frequency, preferred reminder time, and timezone.
- Call create_calendar_event with those values. Do not guess frequency or time — confirm with the user first.
- For "twice daily", the tool automatically creates a morning and evening event.
- After success, confirm the events are set and remind them to note the event_ids.

STRICT RULES:
1. You MUST NOT provide medical diagnoses or prescribe treatments.
2. You MUST NOT interpret lab results as a definitive diagnosis — translate the data and encourage the user to discuss with their doctor.
3. NEVER append a disclaimer sentence to your replies. The UI already shows a persistent disclaimer to the user.
4. If a user describes a life-threatening emergency (chest pain, difficulty breathing, loss of consciousness), immediately tell them to call their local emergency number (911 / 999 / 112).
5. Use the user's medical profile to give personalised, contextually relevant guidance — never to diagnose.
6. You do NOT help find doctors or clinics. If asked, politely explain your focus is on record analysis and medication adherence, and suggest they use a dedicated provider-search service.
"""

        # Primary agent — Gemini 2.5 Flash (best quality)
        self.primary_agent = LlmAgent(
            model="gemini-2.5-flash",
            name="aura_primary",
            instruction=system_instruction,
            tools=list(AGENT_TOOLS),
        )
        self.primary_runner = Runner(
            agent=self.primary_agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

        # Fallback agent — Gemini 2.0 Flash Lite (lighter, less congested)
        self.fallback_agent = LlmAgent(
            model="gemini-2.0-flash-lite",
            name="aura_fallback",
            instruction=system_instruction,
            tools=list(AGENT_TOOLS),
        )
        self.fallback_runner = Runner(
            agent=self.fallback_agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )
        logger.info("AuraAgentService initialised — primary: gemini-2.5-flash, fallback: gemini-2.0-flash-lite")

    def _format_profile(self, medical_profile: Optional[Dict[str, Any]]) -> str:
        """Serialize the user's medical profile into a readable string for the prompt."""
        if not medical_profile:
            return "No medical profile on file for this user."
        try:
            # Truncate daily_logs to the last 7 entries to avoid burning TPM
            # quota by sending the entire health diary on every request.
            if "daily_logs" in medical_profile and isinstance(medical_profile["daily_logs"], list):
                medical_profile = dict(medical_profile)  # shallow copy — don't mutate the original
                medical_profile["daily_logs"] = medical_profile["daily_logs"][-7:]

            mh = medical_profile.get("medical_history", {})
            parts = []
            if mh.get("blood_type"):
                parts.append(f"Blood Type: {mh['blood_type']}")
            if mh.get("allergies"):
                parts.append(f"Allergies: {', '.join(mh['allergies'])}")
            if mh.get("chronic_conditions"):
                parts.append(
                    f"Chronic Conditions: {', '.join(mh['chronic_conditions'])}"
                )
            if mh.get("past_surgeries"):
                parts.append(f"Past Surgeries: {', '.join(mh['past_surgeries'])}")
            if mh.get("family_history"):
                parts.append(f"Family History: {mh['family_history']}")
            dob = medical_profile.get("date_of_birth")
            if dob:
                parts.append(f"Date of Birth: {dob}")
            return (
                "; ".join(parts)
                if parts
                else "Medical profile exists but contains no detailed history."
            )
        except Exception:
            logger.exception("Failed to parse medical profile")
            return "Medical profile could not be parsed."

    async def get_chat_response(
        self,
        message: str,
        session_id: str,
        user_id: str,
        user_db_id: Optional[int] = None,
        medical_profile: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Retrieves the session history and generates a response from the agent.
        Injects the user's medical profile and DB id into ADK session state
        so system prompt placeholders resolve.
        """
        formatted_profile = self._format_profile(medical_profile)
        initial_state = {
            "user_profile_data": formatted_profile,
            "user_db_id": str(user_db_id) if user_db_id is not None else "",
        }
        logger.debug(
            "get_chat_response — user_id: %s, session_id: %s, message_length: %d",
            user_id,
            session_id,
            len(message),
        )

        # Load or create the session using ADK's SessionService
        session = await self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )

        if not session:
            logger.debug(
                "Creating new ADK session: %s for user: %s", session_id, user_id
            )
            session = await self.session_service.create_session(
                app_name=self.app_name,
                user_id=user_id,
                session_id=session_id,
                state=initial_state,
            )
        else:
            logger.debug(
                "Resuming existing ADK session: %s for user: %s", session_id, user_id
            )
            # Refresh profile and identity on every request so updates are picked up
            session.state["user_profile_data"] = formatted_profile
            session.state["user_db_id"] = str(user_db_id) if user_db_id is not None else ""

        # Prepare the user's message in ADK format
        content = types.Content(role="user", parts=[types.Part(text=message)])

        final_response_text = "I'm sorry, I couldn't process your request."
        _capacity_errors = ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
        max_retries = 2

        # ── Phase 1: Primary runner with exponential-backoff retry ──────────
        primary_failed = False
        for attempt in range(max_retries):
            try:
                async for event in self.primary_runner.run_async(
                    user_id=user_id, session_id=session_id, new_message=content
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                            logger.debug(
                                "Primary final response — session_id: %s, length: %d",
                                session_id, len(final_response_text),
                            )
                        return final_response_text
            except Exception as exc:
                err_str = str(exc)
                if any(marker in err_str for marker in _capacity_errors):
                    wait = 2 ** attempt
                    logger.warning(
                        "Primary model capacity error (attempt %d/%d), retrying in %ds — %s",
                        attempt + 1, max_retries, wait, err_str[:120],
                    )
                    await asyncio.sleep(wait)
                    # Reset content for the next attempt — the message object is reusable
                    content = types.Content(role="user", parts=[types.Part(text=message)])
                else:
                    raise  # non-capacity error — propagate immediately
            else:
                break  # ran_async finished without raising — shouldn't reach here, but safe
        else:
            primary_failed = True

        # ── Phase 2: Fallback runner ─────────────────────────────────────────
        if primary_failed:
            logger.warning(
                "Primary exhausted after %d retries — switching to fallback model for session: %s",
                max_retries, session_id,
            )
            try:
                async for event in self.fallback_runner.run_async(
                    user_id=user_id, session_id=session_id, new_message=content
                ):
                    if event.is_final_response():
                        if event.content and event.content.parts:
                            final_response_text = event.content.parts[0].text
                            logger.info(
                                "Fallback final response — session_id: %s, length: %d",
                                session_id, len(final_response_text),
                            )
                        return final_response_text
            except Exception as exc:
                err_str = str(exc)
                if any(marker in err_str for marker in _capacity_errors):
                    logger.warning("Fallback model also at capacity — %s", err_str[:120])
                    raise HTTPException(
                        status_code=503,
                        detail=(
                            "The AI assistant is experiencing high demand across all available models. "
                            "Please wait a moment and try again."
                        ),
                    )
                raise  # unexpected error

        return final_response_text


    async def close(self) -> None:
        """No-op kept for API compatibility. Previously closed the MCP SSE connection."""
        logger.info("AuraAgentService.close() called — nothing to clean up.")


# Create a singleton instance to be used across the app
logger.info("Creating AuraAgentService singleton")
aura_agent = AuraAgentService()
logger.info("AuraAgentService singleton created successfully")
