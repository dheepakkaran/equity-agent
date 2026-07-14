"""Technical analysis agent — LLM reads indicators + ML prediction and produces narrative."""
from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import AgentState, get_llm

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a professional technical analyst. Read the provided indicators "
            "and the ML model's next-day direction prediction, then produce a concise "
            "technical assessment (5-8 sentences). Cover: trend (SMA/EMA), momentum "
            "(RSI, MACD), volatility context (Bollinger position), recent returns, and "
            "how these align or disagree with the ML prediction. Do NOT invent numbers. "
            "Do NOT give buy/sell advice — that comes later.",
        ),
        (
            "human",
            "Ticker: {ticker}\nAs of: {as_of_date}\nClose: {close}\n\n"
            "Indicators (latest row):\n{features_block}\n\n"
            "ML prediction:\n{prediction_block}",
        ),
    ]
)


def _format_features(features: dict[str, float | None]) -> str:
    lines = []
    for key, value in features.items():
        if value is None:
            lines.append(f"- {key}: n/a")
        else:
            lines.append(f"- {key}: {value:.4f}")
    return "\n".join(lines)


def _format_prediction(prediction: dict | None) -> str:
    if not prediction:
        return "No trained model available for this ticker."
    return (
        f"- direction: {prediction.get('direction')}\n"
        f"- confidence: {prediction.get('confidence'):.3f}\n"
        f"- prob_up: {prediction.get('prob_up'):.3f}\n"
        f"- prob_down: {prediction.get('prob_down'):.3f}"
    )


def technical_node(state: AgentState) -> AgentState:
    llm = get_llm(temperature=0.2)
    chain = _PROMPT | llm

    try:
        response = chain.invoke(
            {
                "ticker": state["ticker"],
                "as_of_date": state.get("as_of_date", "n/a"),
                "close": state.get("close", 0.0),
                "features_block": _format_features(state.get("features", {})),
                "prediction_block": _format_prediction(state.get("prediction")),
            }
        )
        return {"technical_analysis": response.content.strip()}
    except Exception as exc:  # noqa: BLE001
        errors = list(state.get("errors", []))
        errors.append(f"technical_agent_error: {exc}")
        return {
            "technical_analysis": "Technical analysis unavailable due to LLM error.",
            "errors": errors,
        }
