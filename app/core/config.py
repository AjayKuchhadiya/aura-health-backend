from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from pathlib import Path


class Settings(BaseSettings):
    """Application settings from environment variables"""

    # Database
    DATABASE_URL: str

    # API Configuration
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "Aura Health Backend"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Firebase
    FIREBASE_CREDENTIALS: Optional[str] = None

    # External Services
    GEMINI_API_KEY: Optional[str] = None

    # Supabase (storage + optional direct queries)
    SUPABASE_URL: Optional[str] = None   # e.g. https://xxxx.supabase.co
    SUPABASE_KEY: Optional[str] = None   # service-role key (kept server-side only)

    # Google Calendar MCP — remote SSE server URL (kept for dev/admin use)
    CALENDAR_MCP_SSE_URL: str = "https://your-calendar-mcp.onrender.com/sse"

    # Google Calendar OAuth — Web Application credentials
    # Download from Google Cloud Console → Credentials → OAuth 2.0 Client IDs
    # Choose type "Web application" and add your redirect URI
    GOOGLE_CALENDAR_CLIENT_ID: Optional[str] = None
    GOOGLE_CALENDAR_CLIENT_SECRET: Optional[str] = None
    # Must match exactly what you registered in Google Cloud Console
    GOOGLE_CALENDAR_REDIRECT_URI: str = "https://aura-health-backend-2xhl.onrender.com/api/v1/calendar/callback"
    # Secret key used to sign the OAuth state token (any random string)
    CALENDAR_STATE_SECRET: str = "change-me-to-a-random-secret"

    # This configuration allows extra fields in .env without crashing
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
