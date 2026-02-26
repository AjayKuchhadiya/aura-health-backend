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

    # AWS/R2 Configuration
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_S3_BUCKET_NAME: Optional[str] = None
    AWS_REGION: str = "us-east-1"

    # External Services
    GOOGLE_VISION_API_KEY: Optional[str] = None

    GEMINI_API_KEY: Optional[str] = None

    # This configuration allows extra fields in .env without crashing
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent.parent.parent / ".env"),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()
