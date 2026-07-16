from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api import analysis, features, health, portfolio, predictions, scan, stocks
from app.config import settings

app = FastAPI(
    title="equity-agent API",
    description="Multi-agent AI platform for equity research",
    version="0.1.0",
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
app.include_router(features.router, prefix="/stocks", tags=["features"])
app.include_router(predictions.router, prefix="/predict", tags=["predictions"])
app.include_router(analysis.router, prefix="/analyze", tags=["analysis"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(scan.router, prefix="/scan", tags=["scan"])

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(INDEX_FILE)


@app.get("/api-info", include_in_schema=False)
async def api_info():
    return {
        "service": "equity-agent",
        "version": "0.1.0",
        "env": settings.app_env,
        "docs": "/docs",
        "health": "/health",
        "dashboard": "/",
    }
