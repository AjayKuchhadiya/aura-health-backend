import logging
import subprocess

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from app.api.v1.router import router
from app.core.database import get_db
from app.core.logging_config import setup_logging

# These imports force SQLAlchemy to "see" your models before the app starts.
# Without this, you get "KeyError: Doctor" because the model isn't registered.
from app.models.user import User
from app.models.doctor import Doctor
from app.models.medication import Medication
from app.models.user_calendar_token import UserCalendarToken

# Initialise logging before anything else
setup_logging()

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Aura Health Backend",
    description="Backend API for Aura Health application",
    version="1.0.0",
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
    },
)

# CORS Configuration — allow all origins
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r".*",
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers (Authorization, etc.)
)

# Include API v1 routes
app.include_router(router, prefix="/api/v1")
logger.info("API v1 router registered at /api/v1")


@app.on_event("startup")
async def on_startup():
    logger.info("Running database migrations...")
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            logger.info("Migrations completed successfully")
        else:
            logger.error("Migration failed:\n%s", result.stderr)
    except Exception as e:
        logger.error("Failed to run migrations: %s", e)
    logger.info("Aura Health Backend is starting up")


@app.on_event("shutdown")
async def on_shutdown():
    from app.services.agent import aura_agent
    await aura_agent.close()
    logger.info("Aura Health Backend is shutting down")


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    logger.debug("Health check requested")
    return {"status": "healthy"}


@app.get("/health/db")
async def db_health_check():
    """
    Lightweight DB keep-alive endpoint.
    Runs a simple SELECT 1 to prevent Supabase from pausing the instance.
    Safe to call unauthenticated — no data is read or written.
    """
    async for db in get_db():
        await db.execute(text("SELECT 1"))
    logger.debug("DB keep-alive ping successful")
    return {"status": "db_alive"}


if __name__ == "__main__":
    import uvicorn

    logger.info("Starting Uvicorn server on 0.0.0.0:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
