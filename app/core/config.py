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

    # Google Calendar MCP — remote SSE server URL
    # Point this at the deployed calendar-mcp service (e.g. on Render)
    CALENDAR_MCP_SSE_URL: str = "https://your-calendar-mcp.onrender.com/sse"

    # This configuration allows extra fields in .env without crashing
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
