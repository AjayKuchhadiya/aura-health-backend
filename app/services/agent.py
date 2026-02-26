import os
from typing import Optional
from google_adk import Agent, SessionManager, Config
from app.core.config import settings

# Ensure the ADK has access to the API key from our environment/settings
os.environ["GEMINI_API_KEY"] = settings.GEMINI_API_KEY


class AuraAgentService:
    def __init__(self):
        # Initialize the ADK Session Manager.
        # By default, this can store sessions in-memory or be configured for a DB.
        self.session_manager = SessionManager()

        # Define the system instructions to shape the agent's persona
        system_instruction = (
            "You are Aura, a helpful and empathetic AI health assistant. "
            "You help users navigate the Aura Health platform, understand basic health queries, "
            "and assist in requesting ambulances. Always advise users to seek professional "
            "medical help for emergencies or serious symptoms."
        )

        # Initialize the ADK Agent (using Gemini 2.5 Flash/Pro as the underlying model)
        self.agent = Agent(
            model="gemini-2.5-flash",
            system_instruction=system_instruction,
            # tools=[...] # We can register Python functions here later (e.g., search_ambulance)
        )

    async def get_chat_response(self, message: str, session_id: str) -> str:
        """
        Retrieves the session history and generates a response from the agent.
        """
        # Load or create the session
        session = self.session_manager.get_or_create_session(session_id)

        # Run the agent with the user's message and current session context
        response = await self.agent.arun(prompt=message, session=session)

        # Save the updated session history
        self.session_manager.save_session(session)

        return response.text


# Create a singleton instance to be used across the app
aura_agent = AuraAgentService()
