from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.sessions import router as sessions_router
from app.config import settings
from app.database import init_db
from app.schemas import ChapterResponse, HealthCheckResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables on startup (zero-tooling SQLite support)
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    description="Aetherfall AI Dungeon Master & Interactive Fiction Engine",
    version="0.1.0",
    lifespan=lifespan,
)

# Permissive CORS for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(sessions_router, prefix="/api")


@app.get("/")
async def root():
    return {
        "message": "Welcome to Aetherfall AI Dungeon Master Engine",
        "app": settings.APP_NAME,
        "status": "online",
    }


@app.get("/health", response_model=HealthCheckResponse)
@app.get("/api/health", response_model=HealthCheckResponse)
async def health_check():
    return HealthCheckResponse(
        status="healthy",
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        database_configured=bool(settings.DATABASE_URL),
    )


@app.get("/api/chapters", response_model=list[ChapterResponse], tags=["chapters"])
async def get_chapters():
    from app.chapters import get_all_chapters
    return [ChapterResponse.model_validate(chap.model_dump()) for chap in get_all_chapters()]
