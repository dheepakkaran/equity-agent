"""News sentiment agent — LLM reads recent headlines and returns sentiment + themes."""
from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from app.agents.base import AgentState, get_llm

_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a financial news analyst. Read the recent headlines about the ticker "
            "and produce a concise sentiment brief (4-6 sentences). Cover: (1) overall "
            "sentiment — BULLISH / BEARISH / MIXED / NEUTRAL, (2) top 2-3 themes driving "
            "the news, (3) any material catalysts or risks visible in the headlines. "
            "Base your reading ONLY on the headlines shown. Do NOT invent facts. "
            "If no headlines are provided, say 'No recent news available.'",
        ),
        (
            "human",
            "Ticker: {ticker}\n\nRecent headlines:\n{headlines_block}",
        ),
    ]
)


def _format_headlines(headlines: list[dict]) -> str:
    if not headlines:
        return "(none)"
    lines = []
    for i, h in enumerate(headlines, 1):
        title = h.get("title", "").strip()
        publisher = h.get("publisher", "unknown")
        published = h.get("published_at", "")
        line = f"{i}. [{publisher}] {title}"
        if published:
            line += f" ({published})"
        lines.append(line)
    return "\n".join(lines)


def news_node(state: AgentState) -> AgentState:
    headlines = state.get("news_headlines") or []

    if not headlines:
        return {"news_summary": "No recent news available for this ticker."}

    llm = get_llm(temperature=0.2)
    chain = _PROMPT | llm

    try:
        response = chain.invoke(
            {
                "ticker": state["ticker"],
                "headlines_block": _format_headlines(headlines),
            }
        )
        return {"news_summary": response.content.strip()}
    except Exception as exc:  # noqa: BLE001
        errors = list(state.get("errors", []))
        errors.append(f"news_agent_error: {exc}")
        return {
            "news_summary": "News sentiment unavailable due to LLM error.",
            "errors": errors,
        }
