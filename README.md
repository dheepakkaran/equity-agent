---
title: Equity Agent
emoji: 📈
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Multi-agent AI equity research with XGBoost + LangGraph (Gemini)
---

# equity-agent

Multi-agent AI platform for equity research, combining an **XGBoost ML brain** with a **LangGraph LLM brain** (Technical + News + Risk agents) that collaborate on stock analysis.

**Live demo:** https://equity-agent-2lpa.onrender.com · **API docs:** https://equity-agent-2lpa.onrender.com/docs

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

Chronological split is critical — random shuffle would leak future data into training.

**Phase 7 improvements** (after 10-ticker bootstrap revealed a systemic DOWN-bias — 9/10 predictions were SHORT):
- **5-day target** instead of 1-day. Daily direction is near-random walk; 5-day trends carry real signal.
- **`scale_pos_weight`** computed from training class balance so the model can't collapse to the majority class.
- **`atr_14` feature** (Wilder ATR) added — real volatility from OHLC that captures gaps, unlike the earlier `|ret_20d|/20` proxy.
- **`bb_mid` dropped** — zero XGBoost importance, collinear with `sma_20`.

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

## Phase 6 — Paper Trading Portfolio

Closes the loop from advisory (`/analyze` produces text + numbers) to execution + P&L tracking. **$1M virtual starting capital** — no real money at risk, but real market data and real system decisions.

```mermaid
flowchart TB
    subgraph AUTO[POST /portfolio/execute/AAPL]
        A1[Run /analyze pipeline]
        A2{Prediction direction?}
        A3{Same-side position open?}
        A4[Skip - already positioned]
        A5[Execute BUY / SHORT<br/>with suggested_shares]
        A1 --> A2
        A2 -->|UP or DOWN| A3
        A3 -->|Yes| A4
        A3 -->|No| A5
    end

    subgraph MANUAL[POST /portfolio/trade]
        M1[BUY / SELL / SHORT / COVER<br/>at latest close]
    end

    A5 --> ENGINE
    M1 --> ENGINE

    subgraph ENGINE[portfolio_service.execute_trade]
        E1[Reject cross-side flip]
        E2[Update cash_balance]
        E3[Upsert position<br/>weighted-avg entry]
        E4[Realize P&L on SELL / COVER]
        E5[Append to trades log]
    end

    ENGINE --> DB[(portfolios · positions · trades)]

    DB --> VIEW[GET /portfolio]
    VIEW --> V1[Cash balance]
    VIEW --> V2[Open positions<br/>mark-to-market from latest close]
    VIEW --> V3[Unrealized P&L]
    VIEW --> V4[Total return %]
```

**Key semantics:**
- **BUY** — opens/adds LONG; cash decreases; weighted-avg entry price maintained
- **SELL** — closes (partial or full) LONG; realizes `(price - avg_entry) × shares`
- **SHORT** — opens/adds SHORT; cash *increases* (proceeds credited); weighted-avg entry
- **COVER** — closes SHORT; realizes `(avg_entry - price) × shares`
- Cross-side flips (e.g. BUY while SHORT open) are rejected — must close first

**Endpoints:** `GET /portfolio` · `POST /portfolio/reset` · `POST /portfolio/trade` · `POST /portfolio/execute/{ticker}` · `GET /portfolio/trades`

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
| GET | `/portfolio` | Current cash, positions, unrealized P&L, total return |
| POST | `/portfolio/reset` | Wipe positions/trades, restore $1M cash |
| POST | `/portfolio/trade` | Manual BUY/SELL/SHORT/COVER at latest close |
| POST | `/portfolio/execute/{ticker}` | Auto-execute the agent's recommended trade |
| GET | `/portfolio/trades` | Trade history (optionally filter by ticker) |
| POST | `/portfolio/snapshot` | Capture today's portfolio state (idempotent per day) |
| GET | `/portfolio/history?days=N` | Equity-curve data + period return |
| POST | `/portfolio/enforce-stops` | Close positions that crossed stop_loss or take_profit |
| POST | `/portfolio/auto-build?budget=X&max_positions=5` | Reset + auto-buy top N high-confidence UP picks |
| GET | `/portfolio/accuracy` | Model track record: overall %, reward points, per-ticker breakdown |
| GET | `/scan?budget=X` | Rank affordable stocks by expected 5-day gain (137-ticker universe) |

## Roadmap

- [x] OHLCV ingestion (idempotent upsert)
- [x] Technical indicators (SMA/EMA/RSI/MACD/BB/returns)
- [x] XGBoost next-day direction prediction with MLflow
- [x] LangGraph multi-agent: Technical + Risk + Synthesis
- [x] News agent (yfinance headlines + Gemini sentiment)
- [x] Paper trading portfolio ($1M virtual capital, auto-execute agent recommendations)
- [x] Model improvements (5-day target, class balance via `scale_pos_weight`, ATR feature, drop `bb_mid`)
- [x] Daily portfolio snapshots (equity curve + period return over any window)
- [x] Stop-loss / take-profit auto-enforcement (autonomous position closure)
- [x] Daily automation via GitHub Actions cron (ingest + enforce + snapshot, no server required)
- [x] Deployment via Docker + Render.com (Dockerfile ready, `${PORT}` respected, `--proxy-headers` set)
- [x] Configurable capital ($100–$100k, auto-scaling risk sizing for demo budgets)
- [x] 137-ticker universe with affordability-filtered scan endpoint
- [x] Prediction tracking + reward points (10 per correct hit + high-confidence bonuses)
- [x] Auto-build portfolio (one click → confidence-weighted allocation across top picks)
- [ ] Langfuse LLM observability
- [ ] Retraining + drift monitoring (Evidently)
- [ ] pgvector for news RAG
- [ ] Tests + CI (pytest + GitHub Actions)
- [ ] HuggingFace Spaces deployment

## License

MIT
