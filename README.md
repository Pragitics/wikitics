# Wikitics

Wikitics is a wiki-first document question-answering application. Users upload documents, the backend extracts source content, generates a wiki-style knowledge layer, indexes wiki and raw chunks, and answers text or voice questions with citations.

The detailed product and architecture source of truth is [`wikitics_detailed_technical_plan.md`](./wikitics_detailed_technical_plan.md). The implementation tracker is [`wikitics_phase_implementation_checklist.md`](./wikitics_phase_implementation_checklist.md).

## Local Docker Setup

1. Copy the environment template:

   ```bash
   cp .env.example .env
   ```

2. Start the stack:

   ```bash
   docker compose up --build
   ```

3. Open the app:

   ```text
   Frontend: http://localhost:5173
   Backend API: http://localhost:8000/docs
   Qdrant: http://localhost:6333/dashboard
   MinIO: http://localhost:9001
   ```

## Development Commands

Backend tests:

```bash
cd backend
pytest
```

Frontend build:

```bash
cd frontend
npm install
npm run build
```

Agent worker smoke test:

```bash
cd agent-worker
python -m compileall .
```

Latency benchmark against a running Docker stack:

```bash
python3 scripts/benchmark_latency.py \
  --base-url http://localhost:8000 \
  --email you@example.com \
  --password password123 \
  --workspace-name "Your Workspace" \
  --max-text-seconds 10 \
  --max-voice-seconds 15 \
  --max-voice-first-audio-seconds 2 \
  --max-llm-seconds 8 \
  --pretty
```

OpenRouter model benchmark for voice-style answers:

```bash
set -a; source .env; set +a
backend/.venv/bin/python scripts/benchmark_openrouter_models.py \
  --base-url http://localhost:8000 \
  --email you@example.com \
  --password password123 \
  --workspace-name "Your Workspace" \
  --models auto \
  --auto-limit 3 \
  --max-first-delta-seconds 5 \
  --max-total-seconds 12 \
  --min-quality-score 50 \
  --pretty
```

## Architecture

The backend follows the DDD and hexagonal architecture in the technical plan:

```text
backend/app/
  domain/
  application/
  ports/
  adapters/
  infrastructure/
  interfaces/
  shared/
```

External systems are kept behind adapters. Docker development uses local deterministic fallbacks where possible, while keeping provider boundaries for Qdrant, OpenRouter, Sarvam, LiveKit, and S3-compatible storage.
