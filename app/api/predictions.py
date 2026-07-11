from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.ml.dataset import InsufficientDataError
from app.ml.predict import ModelNotTrainedError, predict_next_day
from app.ml.train import train_ticker
from app.schemas.prediction import PredictionResponse, TrainResponse

router = APIRouter()


@router.post("/{ticker}/train", response_model=TrainResponse)
async def train_model(ticker: str, db: Session = Depends(get_db)):
    """Train (or retrain) the XGBoost direction classifier for a ticker."""
    try:
        result = train_ticker(ticker, db)
        return result
    except InsufficientDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{ticker}", response_model=PredictionResponse)
async def predict(ticker: str, db: Session = Depends(get_db)):
    """Predict next-day direction (UP/DOWN) using the trained model."""
    try:
        return predict_next_day(ticker, db)
    except ModelNotTrainedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InsufficientDataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
