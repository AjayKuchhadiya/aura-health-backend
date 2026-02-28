import os
import uuid
from typing import Optional

# Correct ADK imports
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types

from app.core.config import settings

# ADK internally looks for GOOGLE_API_KEY
os.environ["GOOGLE_API_KEY"] = settings.GEMINI_API_KEY


class AuraAgentService:
    def __init__(self):
        # Initialize DatabaseSessionService using your existing asyncpg Postgres URL
        self.session_service = DatabaseSessionService(db_url=settings.DATABASE_URL)
        self.app_name = "aura_health"

        # Define the system instructions to shape the agent's persona
        system_instruction = (
            "You are Aura, a helpful and empathetic AI health assistant. "
            "You help users navigate the Aura Health platform, understand basic health queries, "
            "and assist in requesting ambulances. Always advise users to seek professional "
            "medical help for emergencies or serious symptoms."
        )

        # Initialize the ADK Agent (Using Gemini 2.5 Flash)
        self.agent = LlmAgent(
            model="gemini-2.5-flash",
            name="aura_assistant",
            instruction=system_instruction,
        )

        # Initialize the Runner which handles the agent execution and session linking
        self.runner = Runner(
            agent=self.agent,
            app_name=self.app_name,
            session_service=self.session_service,
        )

    async def get_chat_response(
        self, message: str, session_id: str, user_id: str
    ) -> str:
        """
        Retrieves the session history and generates a response from the agent.
        """
        # Load or create the session using ADK's SessionService
        session = await self.session_service.get_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id
        )

        if not session:
            await self.session_service.create_session(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )

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
                break

        return final_response_text


# Create a singleton instance to be used across the app
aura_agent = AuraAgentService()
