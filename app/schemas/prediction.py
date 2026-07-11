from pydantic import BaseModel, Field


class TrainMetrics(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float


class TrainResponse(BaseModel):
    ticker: str
    train_rows: int
    test_rows: int
    metrics: TrainMetrics
    confusion_matrix: list[list[int]] = Field(..., description="[[TN, FP], [FN, TP]]")
    classification_report: dict
    feature_importances: dict[str, float]
    model_path: str


class PredictionResponse(BaseModel):
    ticker: str
    as_of_date: str
    close: float
    prediction: int = Field(..., description="0 = down, 1 = up")
    direction: str = Field(..., description="UP or DOWN")
    confidence: float = Field(..., description="Probability of predicted class")
    prob_up: float
    prob_down: float
    features_used: dict[str, float]
