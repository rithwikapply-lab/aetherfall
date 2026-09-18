from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.schemas import HealthCheckResponse

app = FastAPI(
    title=settings.APP_NAME,
    description="Aetherfall AI Dungeon Master & Interactive Fiction Engine",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {
        "message": "Welcome to Aetherfall AI Dungeon Master Engine",
        "app": settings.APP_NAME,
        "status": "online"
    }


@app.get("/health", response_model=HealthCheckResponse)
@app.get("/api/health", response_model=HealthCheckResponse)
async def health_check():
    return HealthCheckResponse(
        status="healthy",
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        database_configured=bool(settings.DATABASE_URL)
    )
