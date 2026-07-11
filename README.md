# equity-agent

Multi-agent AI platform for equity research, combining ML-based signals with LLM-orchestrated analysis.

## Architecture

Modular monolith with clean service boundaries. Deployable as a single container while maintaining microservices-ready code organization.

## Tech Stack

- **Backend:** FastAPI, SQLAlchemy, Pydantic
- **Database:** PostgreSQL (Neon) with pgvector
- **ML:** XGBoost, MLflow, Evidently AI
- **Agentic AI:** LangGraph with multi-provider LLM support (Gemini, DeepSeek, Qwen, OpenAI)
- **LLMOps:** Langfuse, Ragas
- **CI/CD:** GitHub Actions
- **Deployment:** Hugging Face Spaces

## Features (Roadmap)

- [x] Real-time market data ingestion
- [ ] ML-based price direction prediction (XGBoost)
- [ ] Multi-agent AI analysis (Technical + News + Risk + Coordinator)
- [ ] Paper trading portfolio with P&L tracking
- [ ] Automated weekly model retraining
- [ ] Data & model drift monitoring
- [ ] LLM cost tracking and observability

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
# Fill in DATABASE_URL and API keys in .env

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --reload
```

Open `http://localhost:8000/docs` for interactive API documentation.

## License

MIT
