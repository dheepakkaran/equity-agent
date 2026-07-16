from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

# Load .env into os.environ BEFORE importing modules that use os.getenv (auth).
# pydantic-settings loads .env into its own Settings object only — os.environ
# stays empty for keys we read directly (APP_PASSCODE, APP_SECRET).
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.api import analysis, auth as auth_api, features, health, portfolio, predictions, scan, stocks  # noqa: E402
from app.auth import auth_enabled, is_authenticated  # noqa: E402
from app.config import settings  # noqa: E402

app = FastAPI(
    title="equity-agent API",
    description="Multi-agent AI platform for equity research",
    version="0.1.0",
)


PUBLIC_PATH_PREFIXES = (
    "/auth/",
    "/health",
    "/login",
    "/openapi.json",
    "/docs",
    "/redoc",
    "/favicon.ico",
)


class PasscodeAuthMiddleware(BaseHTTPMiddleware):
    """Redirect unauthenticated HTML requests to /login; return 401 for API."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path == p or path.startswith(p) for p in PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        if not auth_enabled():
            return await call_next(request)

        if is_authenticated(request):
            return await call_next(request)

        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return RedirectResponse(url="/login", status_code=302)
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)


app.add_middleware(PasscodeAuthMiddleware)


app.include_router(auth_api.router, prefix="/auth", tags=["auth"])
app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(stocks.router, prefix="/stocks", tags=["stocks"])
app.include_router(features.router, prefix="/stocks", tags=["features"])
app.include_router(predictions.router, prefix="/predict", tags=["predictions"])
app.include_router(analysis.router, prefix="/analyze", tags=["analysis"])
app.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
app.include_router(scan.router, prefix="/scan", tags=["scan"])

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
LOGIN_FILE = STATIC_DIR / "login.html"


@app.get("/", include_in_schema=False)
async def dashboard():
    return FileResponse(INDEX_FILE)


@app.get("/login", include_in_schema=False)
async def login_page():
    return FileResponse(LOGIN_FILE)


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
