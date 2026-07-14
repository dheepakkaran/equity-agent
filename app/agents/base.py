"""Shared building blocks for the multi-agent layer.

- `get_llm()` returns a configured Gemini chat model.
- `AgentState` is the TypedDict passed between nodes in the LangGraph.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings


def get_llm(temperature: float = 0.2, model: str = "gemini-2.5-flash") -> ChatGoogleGenerativeAI:
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.gemini_api_key,
        temperature=temperature,
    )


class AgentState(TypedDict, total=False):
    ticker: str
    as_of_date: str
    close: float
    features: dict[str, float | None]
    prediction: dict[str, Any] | None
    news_headlines: list[dict[str, Any]]
    news_summary: str
    technical_analysis: str
    risk_assessment: dict[str, Any]
    final_recommendation: str
    errors: list[str]
