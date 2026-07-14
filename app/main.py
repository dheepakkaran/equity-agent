from fastapi import FastAPI

from app.api import analysis, features, health, portfolio, predictions, stocks
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


@app.get("/")
async def root():
    return {
        "service": "equity-agent",
        "version": "0.1.0",
        "env": settings.app_env,
        "docs": "/docs",
        "health": "/health",
    }
