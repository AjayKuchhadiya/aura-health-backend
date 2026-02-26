from fastapi import FastAPI
from app.api.v1.router import router

app = FastAPI(
    title="Aura Health Backend",
    description="Backend API for Aura Health application",
    version="1.0.0"
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
