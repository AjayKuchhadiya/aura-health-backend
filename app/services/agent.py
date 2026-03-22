import logging
import os
import json
import uuid
from typing import Optional, Dict, Any

# Correct ADK imports
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from app.core.config import settings
from app.services.agent_tools import AGENT_TOOLS

logger = logging.getLogger(__name__)

# ADK internally looks for GOOGLE_API_KEY
os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY


class AuraAgentService:
    def __init__(self):
        logger.info("Initialising AuraAgentService")
        # Build the ADK session DB URL with prepared statement caching disabled.
        # This is required when the database sits behind a connection pooler
        # (e.g. PgBouncer / Supabase / Neon) running in transaction or statement
        # pool mode, which does not support asyncpg prepared statements.
        adk_db_url = settings.DATABASE_URL
        # Ensure the scheme is asyncpg-based (ADK requires async dialect)
        if adk_db_url.startswith("postgresql://"):
            adk_db_url = adk_db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif adk_db_url.startswith("postgres://"):
            adk_db_url = adk_db_url.replace("postgres://", "postgresql+asyncpg://", 1)
        # Append prepared_statement_cache_size=0 to disable asyncpg statement caching
        separator = "&" if "?" in adk_db_url else "?"
        adk_db_url = f"{adk_db_url}{separator}prepared_statement_cache_size=0"
        self.session_service = DatabaseSessionService(db_url=adk_db_url)
        self.app_name = "aura_health"

        # Strict Health Navigator persona with guardrails.
        # The {user_profile_data} placeholder is resolved from ADK session state
        # so each user's medical profile is injected automatically.
        system_instruction = (
            "You are Aura, a Health Navigator AI. "
            "You have access to the user's medical profile: {user_profile_data}. "
            "The user's current location is: {user_location}. "
            "Use this location to provide geographically relevant recommendations — "
            "such as mentioning nearby doctors, local emergency numbers, and whether "
            "an Aura platform doctor is based in the user's city or country. "
            "If no location is available, proceed without it. "
            "\n\n"
            "TOOLS AVAILABLE TO YOU:\n"
            "You have the following tools you can actively call to help the user:\n"
            "- search_doctors(specialty, is_available): Search for doctors by specialty on the Aura platform.\n"
            "- get_doctor_details(doctor_id): Get full profile details for a specific doctor.\n"
            "- find_nearest_ambulance(latitude, longitude): Locate the nearest ambulance using GPS coordinates.\n"
            "- request_ambulance(location_description): Dispatch an ambulance to a described location.\n"
            "- assess_emergency_level(symptoms): Triage reported symptoms to determine urgency level.\n"
            "Always proactively use these tools when the user's request can be fulfilled by them. "
            "Do not just describe what you could do — actually call the tool and present the results.\n"
            "\n\n"
            "STRICT RULES YOU MUST ALWAYS FOLLOW:\n"
            "1. You MUST NOT provide medical diagnoses or prescribe treatments under any circumstances.\n"
            "2. You MUST NOT interpret lab results or imaging as a definitive diagnosis.\n"
            "3. Your role is to: translate complex medical jargon into plain language, help the user "
            "organize and articulate their symptoms clearly for a doctor visit, and suggest appropriate "
            "triage actions (e.g., booking a doctor appointment, calling an ambulance, or visiting a pharmacy).\n"
            "4. Always end responses that touch on health concerns with the disclaimer: "
            "'⚠️ Disclaimer: I am an AI Health Navigator, not a licensed medical professional. "
            "This information is not a diagnosis. Please consult a qualified healthcare provider for "
            "medical advice.'\n"
            "5. If the user describes a life-threatening emergency (e.g., chest pain, difficulty breathing, "
            "loss of consciousness), IMMEDIATELY call assess_emergency_level(symptoms) and then "
            "offer to call find_nearest_ambulance or request_ambulance. Always tell them to also "
            "call emergency services (911 or local equivalent).\n"
            "6. Use the user's medical profile (allergies, chronic conditions, blood type, etc.) to provide "
            "personalised, contextually relevant guidance — but never to diagnose."
        )

        # Initialize the ADK Agent (Using Gemini 2.5 Flash) with function-calling tools
        self.agent = LlmAgent(
            model="gemini-2.5-flash",
            name="aura_assistant",
            instruction=system_instruction,
            tools=AGENT_TOOLS,
        )

        # Initialize the Runner which handles the agent execution and session linking
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )
        logger.info("AuraAgentService initialised with model: gemini-2.5-flash")

    def _format_profile(self, medical_profile: Optional[Dict[str, Any]]) -> str:
        """Serialize the user's medical profile into a readable string for the prompt."""
        if not medical_profile:
            return "No medical profile on file for this user."
        try:
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

    def _format_location(self, location: Optional[Dict[str, Any]]) -> str:
        """Serialize the user's location into a readable string for the prompt."""
        if not location:
            return "Location not provided."
        parts = []
        city = location.get("city")
        country = location.get("country")
        lat = location.get("latitude")
        lon = location.get("longitude")
        tz = location.get("timezone")
        if city:
            parts.append(city)
        if country:
            parts.append(country)
        if lat is not None and lon is not None:
            parts.append(f"Coordinates: ({lat}, {lon})")
        if tz:
            parts.append(f"Timezone: {tz}")
        return ", ".join(parts) if parts else "Location not provided."

    async def get_chat_response(
        self,
        message: str,
        session_id: str,
        user_id: str,
        medical_profile: Optional[Dict[str, Any]] = None,
        location: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Retrieves the session history and generates a response from the agent.
        Injects the user's medical profile and location into the ADK session state
        so the system prompt placeholders are resolved correctly.
        """
        formatted_profile = self._format_profile(medical_profile)
        formatted_location = self._format_location(location)
        initial_state = {
            "user_profile_data": formatted_profile,
            "user_location": formatted_location,
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
            # Refresh profile and location on every request so updates are picked up
            session.state["user_profile_data"] = formatted_profile
            session.state["user_location"] = formatted_location

        # Prepare the user's message in ADK format
        content = types.Content(role="user", parts=[types.Part(text=message)])

        final_response_text = "I'm sorry, I couldn't process your request."

        # Run the agent asynchronously. It yields events until the final response is generated.
        async for event in self.runner.run_async(
            user_id=user_id, session_id=session_id, new_message=content
        ):
            # Check if this event contains the final answer from the LLM
            if event.is_final_response():
                if event.content and event.content.parts:
                    final_response_text = event.content.parts[0].text
                    logger.debug(
                        "Final response received — session_id: %s, length: %d",
                        session_id,
                        len(final_response_text),
                    )
                break

        return final_response_text


# Create a singleton instance to be used across the app
logger.info("Creating AuraAgentService singleton")
aura_agent = AuraAgentService()
logger.info("AuraAgentService singleton created successfully")
