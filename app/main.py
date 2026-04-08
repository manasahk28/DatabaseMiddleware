"""
Entry point for the Database Middleware API.

Run with:
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

Interactive docs available at:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routes.api import router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated @app.on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"🚀 Server starting → http://{settings.API_HOST}:{settings.API_PORT}")
    logger.info(f"📊 Database : {settings.DATABASE_TYPE} ({settings.DATABASE_URL or 'unconfigured'})")
    logger.info(f"🤖 SLM     : {settings.SLM_MODEL_NAME}  device={settings.DEVICE}")
    logger.info(f"🔒 SafeMode: {settings.SAFE_MODE}")
    yield
    # Shutdown
    logger.info("👋 Server shutting down…")

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Database Middleware — NLP to SQL",
    description=(
        "A middleware layer that converts natural-language questions into SQL queries "
        "using a Small Language Model (SLM), then executes them against a relational database.\n\n"
        "**Key features**\n"
        "- Schema-aware prompt engineering (DDL injected into every prompt)\n"
        "- Configurable SLM backend (Flan-T5, Phi-2, TinyLlama)\n"
        "- Rule-based fallback when the model is unavailable\n"
        "- SAFE_MODE: restrict execution to SELECT-only queries\n"
        "- Full schema introspection via `/schema`\n"
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------

@app.get("/", tags=["System"])
def root():
    """API home — confirms the service is running."""
    return {
        "message": "Database Middleware API is running!",
        "version": "1.0.0",
        "status": "healthy",
        "docs": "/docs",
        "endpoints": {
            "nlp_to_sql": "POST /api/v1/query",
            "execute_sql": "POST /api/v1/execute",
            "schema":      "GET  /api/v1/schema",
            "tables":      "GET  /api/v1/tables",
            "health":      "GET  /api/v1/health",
        },
    }