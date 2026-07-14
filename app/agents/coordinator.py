"""LangGraph coordinator wiring: data → technical → risk → synthesize.

Data node pulls latest features from Postgres and the trained XGBoost prediction
(if available). Technical & risk agents run in sequence, then a final LLM node
composes a human-readable recommendation.
"""
from __future__ import annotations

import math

import pandas as pd
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

from app.agents.base import AgentState, get_llm
from app.agents.risk import risk_node
from app.agents.technical import technical_node
from app.ml.predict import ModelNotTrainedError, predict_next_day
from app.models.stock import StockOHLCV
from app.services.features import compute_all_features

FEATURE_KEYS = [
    "sma_20", "sma_50", "ema_12", "ema_26", "rsi_14",
    "macd", "macd_signal", "macd_hist",
    "bb_upper", "bb_mid", "bb_lower",
    "ret_1d", "ret_5d", "ret_20d", "volume_sma_20",
]


def _clean(value):
    if value is None:
        return None
    try:
        if math.isnan(value):
            return None
    except TypeError:
        pass
    return float(value)


def make_fetch_node(db: Session):
    """Factory: the data-fetch node needs the DB session bound via closure."""

    def fetch_node(state: AgentState) -> AgentState:
        ticker = state["ticker"].upper()
        rows = (
            db.query(StockOHLCV)
            .filter(StockOHLCV.ticker == ticker)
            .order_by(StockOHLCV.date.desc())
            .limit(120)
            .all()
        )
        if not rows:
            return {
                "errors": [f"no OHLCV rows for {ticker}; fetch via /stocks/{ticker} first"],
                "features": {},
            }

        df = pd.DataFrame(
            [
                {
                    "date": r.date,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in reversed(rows)
            ]
        )
        features_df = compute_all_features(df)
        latest = features_df.iloc[-1]

        features = {k: _clean(latest.get(k)) for k in FEATURE_KEYS}

        as_of = latest["date"]
        as_of_str = as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of)

        prediction = None
        try:
            prediction = predict_next_day(ticker, db)
        except ModelNotTrainedError:
            prediction = None
        except Exception as exc:  # noqa: BLE001
            return {
                "as_of_date": as_of_str,
                "close": float(latest["close"]),
                "features": features,
                "prediction": None,
                "errors": [f"prediction_error: {exc}"],
            }

        return {
            "as_of_date": as_of_str,
            "close": float(latest["close"]),
            "features": features,
            "prediction": prediction,
        }

    return fetch_node


_SYNTH_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are the head of an equity research desk. Read the technical analyst's "
            "note and the risk desk's parameters, then produce ONE final recommendation "
            "for a retail investor. Be concrete. Structure: (1) One-line verdict "
            "(BUY / HOLD / AVOID / SHORT with confidence low/med/high), "
            "(2) Two-sentence rationale referencing the technicals, "
            "(3) Trade plan: entry near current close, exact stop-loss, take-profit, "
            "shares to buy, and total notional. Never invent numbers not in the input.",
        ),
        (
            "human",
            "Ticker: {ticker}\nClose: {close}\n\n"
            "TECHNICAL ANALYST NOTE:\n{technical_analysis}\n\n"
            "RISK DESK PARAMETERS:\n{risk_block}\n\n"
            "ML DIRECTION SIGNAL:\n{prediction_block}",
        ),
    ]
)


def _format_risk(risk: dict) -> str:
    if not risk:
        return "n/a"
    lines = [f"- {k}: {v}" for k, v in risk.items()]
    return "\n".join(lines)


def _format_pred(prediction: dict | None) -> str:
    if not prediction:
        return "No trained model — direction signal unavailable."
    return (
        f"direction={prediction.get('direction')}, "
        f"confidence={prediction.get('confidence'):.3f}"
    )


def synthesize_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0.3)
    chain = _SYNTH_PROMPT | llm
    try:
        response = chain.invoke(
            {
                "ticker": state["ticker"],
                "close": state.get("close", 0.0),
                "technical_analysis": state.get("technical_analysis", "n/a"),
                "risk_block": _format_risk(state.get("risk_assessment", {})),
                "prediction_block": _format_pred(state.get("prediction")),
            }
        )
        return {"final_recommendation": response.content.strip()}
    except Exception as exc:  # noqa: BLE001
        errors = list(state.get("errors", []))
        errors.append(f"synthesize_error: {exc}")
        return {
            "final_recommendation": "Final recommendation unavailable due to LLM error.",
            "errors": errors,
        }


def build_graph(db: Session):
    graph = StateGraph(AgentState)
    graph.add_node("fetch", make_fetch_node(db))
    graph.add_node("technical", technical_node)
    graph.add_node("risk", risk_node)
    graph.add_node("synthesize", synthesize_node)

    graph.set_entry_point("fetch")
    graph.add_edge("fetch", "technical")
    graph.add_edge("technical", "risk")
    graph.add_edge("risk", "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()


def run_analysis(ticker: str, db: Session) -> AgentState:
    app = build_graph(db)
    initial: AgentState = {"ticker": ticker.upper(), "errors": []}
    return app.invoke(initial)
