from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.agents.coordinator import run_analysis
from app.database import get_db
from app.schemas.analysis import AnalysisResponse, Headline, RiskAssessment

router = APIRouter()


@router.post("/{ticker}", response_model=AnalysisResponse)
async def analyze_ticker(ticker: str, db: Session = Depends(get_db)):
    """Run the multi-agent pipeline (Technical + Risk + Synthesis) for a ticker.

    Prerequisite: OHLCV must already be ingested via GET /stocks/{ticker}.
    XGBoost prediction is included if a trained model exists on disk.
    """
    state = run_analysis(ticker, db)

    errors = state.get("errors") or []
    if errors and not state.get("features"):
        raise HTTPException(status_code=404, detail="; ".join(errors))

    risk_raw = state.get("risk_assessment")
    risk = RiskAssessment(**risk_raw) if risk_raw else None

    headlines = [Headline(**h) for h in (state.get("news_headlines") or [])]

    return AnalysisResponse(
        ticker=state["ticker"],
        as_of_date=state.get("as_of_date"),
        close=state.get("close"),
        features=state.get("features") or {},
        prediction=state.get("prediction"),
        news_headlines=headlines,
        news_summary=state.get("news_summary", ""),
        technical_analysis=state.get("technical_analysis", ""),
        risk_assessment=risk,
        final_recommendation=state.get("final_recommendation", ""),
        errors=errors,
    )
