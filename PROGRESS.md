# equity-agent — Progress & Roadmap

**Last updated:** 2026-07-14
**Session summary written by:** Claude (Opus 4.7)
**Repo:** https://github.com/dheepakkaran/equity-agent

---

## 🎯 Project Vision (1-line)

Multi-agent AI equity research platform: **XGBoost ML brain** + **LangGraph LLM brain** collaborating on stock analysis with paper-trading portfolio, drift monitoring, and full LLMOps observability.

---

## ✅ COMPLETED (as of today)

### Phase 1 — Foundation (commit `ca72476`)
- FastAPI skeleton (`app/main.py`)
- Postgres (Neon) connection via SQLAlchemy (`app/database.py`, `app/config.py`)
- Alembic migration → `stocks_ohlcv` table with `(ticker, date)` unique index
- Health endpoint (`app/api/health.py`)
- Yahoo Finance ingestion → idempotent Postgres upsert
  - `GET /stocks/{ticker}?days=N` — fetches + persists
  - `GET /stocks/{ticker}/history?limit=N` — reads from DB
- `.env.example`, `.gitignore` (venv, secrets, ML artifacts excluded)
- Verified: AAPL 5-day fetch → 5 rows persisted, idempotent on repeat

### Phase 2 — Feature Engineering (commit `530a27d`)
- Pure pandas indicator library `app/services/features.py`:
  - `sma(series, window)` — Simple Moving Average
  - `ema(series, window)` — Exponential MA
  - `rsi(series, window=14)` — Relative Strength Index (Wilder smoothing)
  - `macd(series, 12, 26, 9)` — returns macd, signal, histogram
  - `bollinger_bands(series, 20, 2σ)` — upper/mid/lower
  - `returns(series, periods=(1,5,20))` — pct changes
  - `compute_all_features(df)` — one-shot feature build
- Response schema `app/schemas/features.py`
- Endpoint `GET /stocks/{ticker}/features?days=N` (`app/api/features.py`)
- NaN-to-null converter for JSON safety
- Verified: AAPL 90-day features → all indicators computed on latest row

### Phase 3 — XGBoost Prediction Pipeline (uncommitted, tested working)
- `app/ml/dataset.py`:
  - `load_ohlcv_frame(ticker, db)` — pulls all rows for a ticker
  - `build_supervised_frame(df)` — labels target = (next close > today close), drops NaN feature rows
  - `train_test_split_time(df)` — **chronological split** (no shuffle, no leakage)
  - `FEATURE_COLUMNS` — canonical 15-feature list
  - `InsufficientDataError` exception
- `app/ml/train.py`:
  - `train_ticker(ticker, db, ...)` — trains XGBClassifier
  - MLflow experiment logging (params, metrics, model artifact)
  - Local joblib save to `models/{TICKER}_xgb.joblib`
  - Returns metrics + confusion matrix + feature importances
- `app/ml/predict.py`:
  - `predict_next_day(ticker, db)` — loads joblib model, uses latest feature row
  - Returns direction, confidence, prob distribution, feature snapshot used
  - **Bug fixed today:** explicit float-dtype conversion for prediction row (was hitting 500 error due to mixed-dtype Series → object DataFrame)
- Schemas: `app/schemas/prediction.py`
- Endpoints: `app/api/predictions.py`
  - `POST /predict/{ticker}/train` — trains + saves model
  - `GET /predict/{ticker}` — predicts next-day direction
- Requirements updated: `xgboost==2.1.1`, `scikit-learn==1.5.2`, `mlflow==2.16.2`
- `.gitignore` updated to exclude `models/`
- Increased `days` max on `/stocks` endpoint: 365 → 3650
- Verified: AAPL trained on ~2yr of data (360 train / 91 test rows), prediction endpoint returns valid response

### Model results (AAPL, first attempt)
- Accuracy: **45%** (worse than 50% baseline)
- F1 (UP class): 0.36
- Confusion matrix: `[[27, 15], [35, 14]]` — heavy DOWN-bias
- Feature importances flat (~0.06-0.08 across all)
- `bb_mid` = 0 importance (redundant with sma_20 — cleanup opportunity)
- **Expected**: daily direction prediction is inherently noisy; 45% on first pass with only single-ticker training is normal

### Phase 4 — LangGraph Multi-Agent Orchestrator (committed 2026-07-14)
- `app/agents/base.py`:
  - `get_llm(temperature, model)` — Gemini factory (`gemini-1.5-flash` default)
  - `AgentState` TypedDict (ticker, features, prediction, technical_analysis, risk_assessment, final_recommendation, errors)
- `app/agents/technical.py`:
  - `technical_node(state)` — LLM reads latest features + ML prediction → 5-8 sentence technical narrative
  - Prompt forbids invented numbers and buy/sell calls (that's the coordinator's job)
- `app/agents/risk.py`:
  - `risk_node(state)` — pure Python, no LLM
  - Volatility proxy: `|ret_20d| / 20` clamped to [0.5%, 10%]
  - Stop-loss = 2× daily vol, take-profit = 3× daily vol (1.5 R:R)
  - Kelly-lite sizing: risk budget = 2% × $10k × (confidence - 0.5) × 2
- `app/agents/coordinator.py`:
  - `build_graph(db)` — LangGraph StateGraph: `fetch → technical → risk → synthesize → END`
  - `fetch_node` — pulls 120 rows from Postgres, computes features, calls `predict_next_day` if model exists (gracefully handles `ModelNotTrainedError`)
  - `synthesize_node` — head-of-desk LLM composes final BUY/HOLD/AVOID verdict + trade plan
  - `run_analysis(ticker, db)` — public entrypoint
- Schemas: `app/schemas/analysis.py` (`AnalysisResponse`, `RiskAssessment`)
- Endpoint: `POST /analyze/{ticker}` (`app/api/analysis.py`)
- Requirements added: `langgraph==0.2.76`, `langchain==0.3.27`, `langchain-core==0.3.72`, `langchain-google-genai==2.1.0`
- **News agent deliberately deferred** — needs external API decision (NewsAPI vs Alpha Vantage vs scraping)
- **Verified end-to-end on AAPL 2026-07-14:** technical narrative reconciled bullish trend with DOWN ML signal via Bollinger upper-band proximity; risk agent produced correct SHORT stop-loss above entry; coordinator synthesised SHORT trade plan with entry/stop/target/shares/notional consistent
- **Gemini model gotcha:** `gemini-1.5-flash` returns 404 on v1beta — must use `gemini-2.5-flash` (fixed in `app/agents/base.py`)

### Phase 5 — News Agent (committed, verified 2026-07-14)
- `app/services/news.py`:
  - `fetch_headlines(ticker, limit=10)` — uses `yfinance.Ticker(ticker).news` (no new API key)
  - `_extract_headline(item)` — handles both new-shape (`content.title`, `provider.displayName`, `pubDate`) and legacy-shape (`title`, `publisher`, `providerPublishTime`)
  - Returns [] on any failure (safe for empty-news tickers)
- `app/agents/news.py`:
  - `news_node(state)` — LLM (Gemini) reads headlines → 4-6 sentence sentiment brief with BULLISH/BEARISH/MIXED/NEUTRAL verdict + top themes + catalysts
  - Skips LLM call if headlines empty (returns "No recent news available.")
- Updated `AgentState` in `base.py` with `news_headlines` + `news_summary`
- Coordinator graph now: `fetch → news → technical → risk → synthesize`
- `fetch_node` also loads headlines during data-fetch step
- Synthesize prompt updated to consume news alongside technical + risk + ML signal
- Response schema: added `Headline` model + `news_headlines`/`news_summary` fields to `AnalysisResponse`
- **Verified on AAPL 2026-07-14:** yfinance returned 10 headlines (KeyBanc Underweight cut, iPhone weakness, retail selling); news agent produced correct BEARISH verdict; synthesis reconciled bullish technicals vs bearish news+ML into a coherent SHORT recommendation. Full 3-agent pipeline operational.

### Phase 6 — Paper Trading Portfolio (uncommitted, 2026-07-14)
- **$1M virtual starting capital.**
- Alembic migration `a1b2c3d4e5f6_create_portfolio_tables.py`: creates `portfolios`, `positions`, `trades` tables.
- Models: `app/models/portfolio.py` — `Portfolio`, `Position`, `Trade`; unique constraint `(portfolio_id, ticker, side)` so LONG and SHORT can coexist on different tickers but not double-open same side.
- Service: `app/services/portfolio_service.py`:
  - Actions: BUY / SELL / SHORT / COVER
  - BUY: cash decrease, weighted-avg entry price, opens/adds LONG
  - SELL: cash increase, realizes `(price - avg_entry) × shares`, deletes position if shares hit 0
  - SHORT: cash increase (proceeds), opens/adds SHORT
  - COVER: cash decrease, realizes `(avg_entry - price) × shares`
  - Cross-side flips rejected (must close opposite side first)
- Endpoints (`app/api/portfolio.py`):
  - `GET /portfolio` — cash + open positions + unrealized P&L + total return
  - `POST /portfolio/reset` — wipe positions/trades, restore $1M cash
  - `POST /portfolio/trade` — manual BUY/SELL/SHORT/COVER at latest close
  - `POST /portfolio/execute/{ticker}` — auto-run `/analyze/{ticker}`, execute the trade plan (skips if 0 shares, already same-side position, or no ML signal)
  - `GET /portfolio/trades` — trade history, optional ticker filter
- Risk agent `DEFAULT_PORTFOLIO_USD`: $10k → **$1M** (suggested_shares scales 100×)
- Router wired in `app/main.py`
- **Not yet migrated/tested** — run `alembic upgrade head` first

---

## 🚧 PENDING WORK — Ordered by priority

### 🔴 IMMEDIATE (next session start here)

**Migrate DB + test Phase 6 (paper trading), then commit.**
```powershell
.\venv\Scripts\Activate.ps1
alembic upgrade head    # creates portfolios/positions/trades tables

# uvicorn should auto-reload; if stopped:
uvicorn app.main:app --reload

# Test sequence:
# 1. GET  http://localhost:8000/portfolio         → $1M cash, no positions
# 2. POST http://localhost:8000/portfolio/execute/AAPL   → auto-executes agent trade plan
# 3. GET  http://localhost:8000/portfolio         → open SHORT position, unrealized P&L computed
# 4. GET  http://localhost:8000/portfolio/trades  → trade history
```

If green:
```powershell
git add alembic app/models/portfolio.py app/schemas/portfolio.py app/services/portfolio_service.py app/api/portfolio.py app/main.py app/agents/risk.py PROGRESS.md README.md
git commit -m "Add paper trading portfolio ($1M virtual capital) + auto-execute agent recommendations"
git push
```

---

### 🟢 Later phases (roadmap order)

**Task 5: Paper trading portfolio**
- Tables: `portfolio`, `positions`, `trades`
- Alembic migration
- Endpoints: buy/sell, view P&L, position history
- Use current model + agent recommendations to auto-simulate trades

**Task 6: Model improvement iteration**
- Multi-day direction target (5-day, 20-day) — less noise
- Multi-ticker training (SPY, QQQ, sector ETFs, top 10 stocks)
- Class balance handling (scale_pos_weight or SMOTE)
- Remove redundant `bb_mid` feature
- Feature engineering: volatility (ATR), candlestick patterns, log returns
- Hyperparameter tuning (Optuna)

**Task 7: LLMOps observability**
- Langfuse integration for LLM call tracking
- Ragas for RAG evaluation (if adding news RAG)
- LLM cost per-agent, per-request logging

**Task 8: Automated retraining + drift monitoring**
- Weekly retraining cron job
- Evidently AI drift reports (feature drift, prediction drift, target drift)
- MLflow model registry (staging → production promotion)

**Task 9: pgvector integration**
- Store news article embeddings
- Semantic retrieval for news agent RAG

**Task 10: CI/CD + Deployment**
- GitHub Actions: lint (ruff), format check (black), test (pytest)
- Dockerfile
- HuggingFace Spaces deployment (with `HF_TOKEN` in `.env`)

**Task 11: Tests** *(should probably move earlier)*
- pytest for existing endpoints
- Fixture: temporary SQLite DB for isolated tests
- Feature computation unit tests

---

## 📂 Current file tree (post-XGBoost)

```
equity-agent/
├── .env                       # (gitignored) DATABASE_URL, GEMINI_API_KEY etc.
├── .env.example
├── .gitignore
├── PROGRESS.md                # ← this file
├── README.md
├── alembic.ini
├── alembic/
│   └── versions/
│       └── 48259e2cfe17_create_stocks_ohlcv_table.py
├── app/
│   ├── __init__.py
│   ├── main.py                # FastAPI + 4 routers registered
│   ├── config.py              # Pydantic settings
│   ├── database.py            # SQLAlchemy engine + Session
│   ├── api/
│   │   ├── health.py
│   │   ├── stocks.py          # /stocks/{ticker}, /stocks/{ticker}/history
│   │   ├── features.py        # /stocks/{ticker}/features
│   │   ├── predictions.py     # /predict/{ticker}/train, /predict/{ticker}
│   │   └── analysis.py        # /analyze/{ticker} (multi-agent)
│   ├── agents/                # LangGraph multi-agent layer (Phase 4-5)
│   │   ├── __init__.py
│   │   ├── base.py            # LLM factory + AgentState
│   │   ├── technical.py       # LLM technical analysis node
│   │   ├── news.py            # LLM news sentiment node (Phase 5)
│   │   ├── risk.py            # Rule-based risk node
│   │   └── coordinator.py     # StateGraph: fetch→news→technical→risk→synthesize
│   ├── models/
│   │   └── stock.py           # StockOHLCV table
│   ├── schemas/
│   │   ├── stock.py
│   │   ├── features.py
│   │   ├── prediction.py
│   │   └── analysis.py
│   ├── services/
│   │   ├── data_service.py    # Yahoo Finance OHLCV + upsert
│   │   ├── features.py        # Technical indicators
│   │   └── news.py            # yfinance headlines fetcher (Phase 5)
│   └── ml/
│       ├── __init__.py
│       ├── dataset.py
│       ├── train.py
│       └── predict.py
├── models/                    # (gitignored) trained joblib models
│   └── AAPL_xgb.joblib
├── mlruns/                    # (gitignored) MLflow experiment logs
├── requirements.txt
├── scripts/
│   └── test_db_connection.py
└── tests/
    └── __init__.py            # (empty — no real tests yet)
```

---

## 🧪 Verified working endpoints

| Method | Path | Status |
|--------|------|--------|
| GET | `/health` | ✅ |
| GET | `/stocks/{ticker}?days=N` | ✅ |
| GET | `/stocks/{ticker}/history?limit=N` | ✅ |
| GET | `/stocks/{ticker}/features?days=N` | ✅ |
| POST | `/predict/{ticker}/train` | ✅ |
| GET | `/predict/{ticker}` | ✅ (bug fixed today) |
| POST | `/analyze/{ticker}` | ✅ Verified on AAPL |

---

## 🗃️ Database state (Neon Postgres)

- `stocks_ohlcv` table exists (Alembic migration applied)
- **Data present:** AAPL, ~2 years of history (from `days=730` fetch)
- No other tickers loaded yet
- No portfolio/trades tables yet

---

## 🤖 Trained models

- `models/AAPL_xgb.joblib` — 45% accuracy, DOWN-biased (needs improvement — see Task 6)

---

## 🔧 Environment

- Python venv: `.\venv\`
- Activation: `.\venv\Scripts\Activate.ps1`
- Server: `uvicorn app.main:app --reload`
- Swagger: http://localhost:8000/docs

---

## 📝 Session-level context / user preferences

*(Also stored in `~/.claude/projects/.../memory/` — auto-loaded next session)*

- User communicates in Tanglish (Tamil-English mix)
- User prefers to run shell commands themselves — Claude writes code, hands over terminal commands
- User dislikes repeated confirmation asks; be decisive after initial agreement
- Foundation was solid → we're comfortable moving faster now

---

## 🚀 Naalaiku session-la enna solla vendiyadhu (for user)

Just say: **"Padi PROGRESS.md file-a, adhu vachu continue pannu"**

Claude will:
1. Read this file
2. See uncommitted XGBoost pipeline → suggest committing first
3. Ask you to pick: Task 4 (multi-agent) / Task 6 (improve model) / Task 11 (tests) / other
4. Start executing
