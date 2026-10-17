# Wikitics

Wikitics turns uploaded documents into a searchable workspace wiki. It extracts document content, generates linked wiki pages, and answers text or voice questions with source citations.

## Highlights

- Upload PDF, DOCX, and text documents
- Build a workspace-specific wiki from source material
- Ask cited questions across documents and wiki pages
- Continue conversations with memory-aware answers
- Use text or voice interactions

## Stack

- Frontend: React, TypeScript, Vite, Tailwind CSS
- Backend: FastAPI, SQLAlchemy, PostgreSQL
- AI services: OpenRouter and Sarvam
- Realtime voice: LiveKit
- Local development: Docker Compose

## Run locally

Prerequisites: Docker Desktop and Docker Compose.

```bash
cp .env.example .env
docker compose up --build
```

Open the app at [http://localhost:5173](http://localhost:5173). The API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

Add valid `OPENROUTER_API_KEY` and `SARVAM_API_KEY` values to `.env` to enable AI-powered wiki generation and voice features.

## Development

```bash
# Frontend
cd frontend
npm install
npm run dev

# Backend tests
cd ../backend
pytest
```

## Deployment

The frontend can be deployed to Vercel from the `frontend` directory. Configure `VITE_API_BASE_URL` in Vercel with the public URL of the deployed backend.

The backend requires a persistent PostgreSQL database, persistent object storage, and the service credentials defined in `.env`; deploy it to a service that supports long-running Python applications and configure its environment there.
