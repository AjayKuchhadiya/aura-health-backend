from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1.router import router

# These imports force SQLAlchemy to "see" your models before the app starts.
# Without this, you get "KeyError: Doctor" because the model isn't registered.
from app.models.user import User
from app.models.doctor import Doctor

app = FastAPI(
    title="Aura Health Backend",
    description="Backend API for Aura Health application",
    version="1.0.0",
    swagger_ui_init_oauth={
        "usePkceWithAuthorizationCodeGrant": True,
    }
)

# CORS Configuration
origins = [
    "http://localhost:3000",  # React/Next.js default port
    "http://127.0.0.1:3000",
    # Add your production frontend URL here later, e.g., "https://myapp.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, etc.)
    allow_headers=["*"],  # Allows all headers (Authorization, etc.)
)

# Include API v1 routes
app.include_router(router, prefix="/api/v1")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)