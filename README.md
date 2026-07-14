# equity-agent

Multi-agent AI platform for equity research, combining an **XGBoost ML brain** with a **LangGraph LLM brain** (Technical + News + Risk agents) that collaborate on stock analysis.

---

## Overall Architecture

```mermaid
flowchart LR
    Y[Yahoo Finance] -->|OHLCV| DB[(Postgres / Neon)]
    DB --> FE[Feature Engineering<br/>SMA · EMA · RSI · MACD · BB · Returns]
    FE --> ML[XGBoost<br/>Next-day direction]
    FE --> AG[LangGraph<br/>Multi-Agent Orchestrator]
    YN[yfinance news] --> AG
    ML --> AG
    AG --> API[FastAPI<br/>REST endpoints]
    API --> U[User / Client]
```

The system is a **modular monolith**: one FastAPI container, but organized as independent services (data, features, ML, agents) that could be extracted into microservices later. ML alone is commodity; multi-agent LLM analysis on top of ML is the differentiator.

---

## Phase 1 — Data Ingestion

```mermaid
flowchart LR
    U[User request] --> API[GET /stocks/AAPL?days=730]
    API --> YF[yfinance<br/>fetch OHLCV]
    YF --> UP[Upsert<br/>ON CONFLICT DO NOTHING]
    UP --> DB[(stocks_ohlcv<br/>UNIQUE ticker,date)]
    DB --> API
    API --> R[JSON<br/>rows persisted]
```

Idempotent ingest: repeat calls are safe, no duplicates. Postgres unique constraint on `(ticker, date)` enforces this at the DB layer. Alembic manages the schema.

**Endpoints:** `GET /stocks/{ticker}?days=N`, `GET /stocks/{ticker}/history?limit=N`

---

## Phase 2 — Feature Engineering

```mermaid
flowchart LR
    DB[(stocks_ohlcv)] --> LOAD[Load N rows<br/>oldest → newest]
    LOAD --> IND[Indicator Library<br/>app/services/features.py]
    IND --> SMA[SMA 20/50]
    IND --> EMA[EMA 12/26]
    IND --> RSI[RSI 14<br/>Wilder smoothing]
    IND --> MACD[MACD 12/26/9]
    IND --> BB[Bollinger Bands<br/>20, 2σ]
    IND --> RET[Returns<br/>1d / 5d / 20d]
    SMA --> OUT[Feature DataFrame]
    EMA --> OUT
    RSI --> OUT
    MACD --> OUT
    BB --> OUT
    RET --> OUT
    OUT --> API[GET /stocks/AAPL/features]
```

Pure pandas — no I/O, no DB. **Shared by both the ML pipeline and the Technical agent** so indicator logic never drifts between them.

**Endpoint:** `GET /stocks/{ticker}/features?days=N`

---

## Phase 3 — XGBoost ML Pipeline

```mermaid
flowchart TB
    subgraph TRAIN[Training · POST /predict/AAPL/train]
        T1[Load OHLCV from DB] --> T2[Compute all features]
        T2 --> T3[Build supervised frame<br/>target = next_close > close]
        T3 --> T4[Chronological split<br/>no shuffle, no leakage]
        T4 --> T5[XGBClassifier.fit]
        T5 --> T6[Log to MLflow<br/>params · metrics · artifact]
        T5 --> T7[joblib.dump<br/>models/AAPL_xgb.joblib]
    end

    subgraph PRED[Prediction · GET /predict/AAPL]
        P1[Load model from disk] --> P2[Compute latest features]
        P2 --> P3[predict_proba]
        P3 --> P4[direction · confidence · prob_up · prob_down]
    end
```

Chronological split is critical — random shuffle would leak future data into training. AAPL first-pass accuracy is 45% (below the 50% baseline, DOWN-biased). Daily direction is genuinely noisy signal; improvement roadmap is multi-ticker training + 5-day target + class balance.

**Endpoints:** `POST /predict/{ticker}/train`, `GET /predict/{ticker}`

---

## Phase 4 & 5 — LangGraph Multi-Agent Orchestrator

The heart of the system. Every `/analyze/{ticker}` call runs this StateGraph:

```mermaid
flowchart TB
    START([POST /analyze/AAPL]) --> FETCH

    subgraph FETCH[fetch node]
        F1[Query DB<br/>120 rows OHLCV]
        F2[Compute features]
        F3[Load XGBoost model<br/>if trained]
        F4[yfinance headlines<br/>top 10]
        F1 --> F2 --> F3 --> F4
    end

    FETCH --> NEWS

    subgraph NEWS[news agent · LLM]
        N1[Gemini reads headlines]
        N2[Verdict: BULLISH / BEARISH / MIXED / NEUTRAL]
        N3[Top themes + catalysts]
        N1 --> N2 --> N3
    end

    NEWS --> TECH

    subgraph TECH[technical agent · LLM]
        T1[Gemini reads<br/>features + ML prediction]
        T2[Analyst note<br/>trend · momentum · volatility]
        T1 --> T2
    end

    TECH --> RISK

    subgraph RISK[risk agent · rules]
        R1["Volatility proxy<br/>|ret_20d| / 20"]
        R2["Stop-loss = 2× daily vol"]
        R3["Take-profit = 3× daily vol"]
        R4["Kelly-lite sizing:<br/>2% × 10k × (conf - 0.5) × 2"]
        R1 --> R2
        R1 --> R3
        R1 --> R4
    end

    RISK --> SYNTH

    subgraph SYNTH[synthesize · LLM]
        S1[Head-of-desk Gemini]
        S2[Reconcile technicals + news + ML]
        S3[Verdict: BUY / HOLD / AVOID / SHORT]
        S4[Concrete trade plan<br/>entry · stop · target · shares]
        S1 --> S2 --> S3 --> S4
    end

    SYNTH --> END([JSON response])
```

**Why this works:** each agent has a narrow job with a targeted prompt. The synthesizer sees all three outputs plus the raw ML signal, and calls out conflicts explicitly (e.g. bullish technicals vs bearish news → often surfaces the more informative signal wins). Rule-based risk agent stays deterministic — position sizing shouldn't be an LLM guess.

**Endpoint:** `POST /analyze/{ticker}`

### Example verified output (AAPL, 2026-07-14)

- **News agent:** BEARISH — KeyBanc downgrade to Underweight, iPhone weakness cited, retail investors cashing out
- **Technical agent:** Bullish price above all MAs and momentum positive, but price near upper Bollinger Band flags reversal risk
- **ML prediction:** DOWN with 71.6% confidence
- **Risk agent:** stop-loss 318.47, take-profit 310.59, 27 shares, $8,513 notional
- **Final synthesis:** SHORT with medium-high confidence — synthesizer explicitly reconciled the bullish technicals against bearish news + bearish ML

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| API | FastAPI + Pydantic v2 | Async, typed, auto-docs at `/docs` |
| DB | Postgres (Neon) + SQLAlchemy + Alembic | Managed Postgres free tier + typed ORM + versioned migrations |
| ML | XGBoost + scikit-learn + MLflow | Tabular workhorse + experiment tracking |
| Agents | LangGraph + langchain-google-genai | Explicit state machine, Gemini 2.5 Flash as LLM |
| Data | yfinance + pandas | Zero-key data source for OHLCV + news |

## Local Setup

```powershell
# Clone
git clone https://github.com/dheepakkaran/equity-agent.git
cd equity-agent

# Virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure
copy .env.example .env
# Fill in DATABASE_URL and GEMINI_API_KEY in .env

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for interactive API documentation.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness check |
| GET | `/stocks/{ticker}?days=N` | Fetch OHLCV from Yahoo → persist to Postgres |
| GET | `/stocks/{ticker}/history?limit=N` | Read persisted OHLCV |
| GET | `/stocks/{ticker}/features?days=N` | Compute technical indicators |
| POST | `/predict/{ticker}/train` | Train XGBoost, log to MLflow |
| GET | `/predict/{ticker}` | Predict next-day direction |
| POST | `/analyze/{ticker}` | Full multi-agent analysis + trade plan |

## Roadmap

- [x] OHLCV ingestion (idempotent upsert)
- [x] Technical indicators (SMA/EMA/RSI/MACD/BB/returns)
- [x] XGBoost next-day direction prediction with MLflow
- [x] LangGraph multi-agent: Technical + Risk + Synthesis
- [x] News agent (yfinance headlines + Gemini sentiment)
- [ ] Paper trading portfolio (positions, trades, P&L)
- [ ] Model improvements (multi-ticker, 5-day target, class balance)
- [ ] Langfuse LLM observability
- [ ] Retraining + drift monitoring (Evidently)
- [ ] pgvector for news RAG
- [ ] Tests + CI (pytest + GitHub Actions)
- [ ] HuggingFace Spaces deployment

## License

MIT
