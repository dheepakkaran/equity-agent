from datetime import datetime, timezone

from fastapi import APIRouter

router = APIRouter()


@router.get("")
async def health_check():
    return {
        "status": "healthy",
        "service": "equity-agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
