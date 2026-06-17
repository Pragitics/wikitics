# Wikitics Phase Implementation Checklist

Source of truth: [`wikitics_detailed_technical_plan.md`](./wikitics_detailed_technical_plan.md)

This file is the execution tracker for implementing Wikitics. Keep it updated as work progresses. Each phase must pass its testing gate before the next phase is considered complete.

## Success Criteria

- [x] Users can upload supported documents.
- [x] Uploaded documents are extracted into a canonical extracted layer.
- [x] The system generates a wiki-style knowledge layer from uploaded documents.
- [x] Wiki sections and raw source chunks are indexed for retrieval.
- [x] Text Q&A answers questions using only uploaded document context.
- [x] Answers include source citations where available.
- [x] Voice Q&A works through a voice session path.
- [x] The whole application runs through Docker Compose.
- [x] Retrieval is always filtered by `user_id` and `workspace_id`.
- [x] Raw documents remain the source of truth.

## Tracking Rules

- `[ ]` Not started
- `[~]` In progress
- `[x]` Complete
- `[!]` Blocked or needs review

Do not mark a phase complete until its implementation checklist and testing checklist are both complete.

---

## Phase 0 - Repository, Docker Cleanup, and Planning

Goal: prepare the repo and convert the technical plan into an implementation roadmap.

Implementation checklist:

- [x] Stop existing running Docker containers before implementation.
- [x] Read `wikitics_detailed_technical_plan.md`.
- [x] Create this phase-wise implementation checklist.
- [x] Add project-level `README.md` with local setup and Docker instructions.
- [x] Add `.env.example` covering backend, frontend, agent, database, MinIO/S3, LiveKit, Sarvam, and OpenRouter settings.
- [x] Add `.gitignore` for Python, Node, Docker, local storage, build outputs, and secrets.

Testing checklist:

- [x] Confirm `docker ps` has no previously running project containers.
- [x] Confirm the phase checklist matches the technical plan sections.
- [x] Confirm no secrets are committed.

Phase 0 test notes:

```text
2026-05-23:
- `docker ps --format '{{.ID}} {{.Names}}'` returned no running containers.
- Checklist phases were created from the technical plan sections and MVP order.
- Secret scan found only placeholder values in `.env.example`.
```

---

## Phase 1 - Dockerized Project Foundation

Goal: scaffold the full application structure and Docker runtime described in the plan.

Planned components:

- FastAPI backend
- React + Tailwind frontend
- Agent worker
- PostgreSQL
- MinIO-compatible object storage

Implementation checklist:

- [x] Create `docker-compose.yml`.
- [x] Create backend Dockerfile.
- [x] Create frontend Dockerfile.
- [x] Create agent worker Dockerfile.
- [x] Add Postgres service.
- [x] Add optional MinIO service for S3-compatible storage testing.
- [x] Add backend service wired to Postgres, local storage, optional S3-compatible storage, LiveKit, Sarvam, and OpenRouter.
- [x] Add frontend service wired to backend API URL.
- [x] Add agent worker service wired to backend, LiveKit, Sarvam, and OpenRouter config.
- [x] Create backend DDD/hexagonal folder structure:
  - [x] `domain/`
  - [x] `application/`
  - [x] `ports/`
  - [x] `adapters/`
  - [x] `infrastructure/`
  - [x] `interfaces/`
  - [x] `shared/`
- [x] Create frontend folder structure:
  - [x] `components/`
  - [x] `features/`
  - [x] `services/`
  - [x] `hooks/`
  - [x] `stores/`
  - [x] `types/`
- [x] Create agent worker folder structure:
  - [x] `agents/`
  - [x] `adapters/`
  - [x] `config.py`
  - [x] `main.py`

Testing checklist:

- [x] `docker compose config` passes.
- [x] Backend package imports successfully.
- [x] Frontend dependency install/build command starts without missing files.
- [x] Agent worker imports successfully.
- [x] Docker services start without container crash loops.

Phase 1 test notes:

```text
2026-05-23:
- `docker compose config` passed.
- `python -m compileall backend/app` passed.
- `python -m compileall agent-worker` passed.
- `npm install` and `npm run build` passed in `frontend/`.
- `docker compose up -d --build` started the app stack without crash loops.
```

---

## Phase 2 - Backend Core, Database, Auth, and Workspaces

Goal: implement the core backend foundation with domain boundaries, persistence, authentication, and workspace isolation.

Relevant plan sections:

- Section 5.1 User Management
- Section 14 Backend Architecture
- Section 18 Database Design
- Section 20.1 Auth APIs
- Section 20.2 Workspace APIs
- Section 26 Security Design

Implementation checklist:

- [x] Define backend settings and environment loading.
- [x] Configure structured logging.
- [x] Configure SQLAlchemy engine and sessions.
- [x] Create database models:
  - [x] `users`
  - [x] `workspaces`
  - [x] `workspace_members`
  - [x] `documents`
  - [x] `document_versions`
  - [x] `extracted_documents`
  - [x] `wiki_pages`
  - [x] `wiki_links`
  - [x] `chunks`
  - [x] `conversations`
  - [x] `messages`
  - [x] `citations`
  - [x] `voice_sessions`
- [x] Add database migration/init path.
- [x] Define domain entities and value objects for users, workspaces, and membership.
- [x] Define repository ports.
- [x] Implement SQLAlchemy repository adapters.
- [x] Implement password hashing.
- [x] Implement token-based authentication.
- [x] Implement current-user dependency.
- [x] Implement workspace access validation.
- [x] Implement auth APIs:
  - [x] `POST /api/auth/register`
  - [x] `POST /api/auth/login`
  - [x] `POST /api/auth/logout`
  - [x] `GET /api/auth/me`
- [x] Implement workspace APIs:
  - [x] `POST /api/workspaces`
  - [x] `GET /api/workspaces`
  - [x] `GET /api/workspaces/{workspace_id}`
  - [x] `DELETE /api/workspaces/{workspace_id}`
- [x] Ensure route handlers call application use cases, not raw infrastructure code.

Testing checklist:

- [x] Unit test password hashing and token creation.
- [x] Unit test workspace access rules.
- [x] API test user registration.
- [x] API test login.
- [x] API test `/api/auth/me`.
- [x] API test workspace creation.
- [x] API test workspace deletion and cleanup.
- [x] API test workspace list isolation between users.
- [x] API test unauthorized workspace access returns an error.
- [x] Docker integration test backend connects to Postgres.

Phase 2 test notes:

```text
2026-05-23:
- Backend tests passed: `6 passed`.
- Docker health check passed: `GET /health` returned `{"status":"ok"}`.
- Workspace isolation was verified in API tests.

2026-05-24:
- Backend tests passed with expanded coverage: `PYTHONPATH=backend backend/.venv/bin/pytest` -> `31 passed`.
- Structured JSON logging now includes request IDs, and API responses include `X-Request-ID`.
- Added user/workspace/membership domain entities and SQLAlchemy repository adapters.
- Added workspace access and repository adapter tests.
- Added owner-only workspace deletion, cleanup of workspace-owned data, vector removal, storage prefix cleanup, and API integration coverage.
```

---

## Phase 3 - Document Upload, Storage, and Extraction

Goal: upload PDF, DOCX, TXT, and Markdown files, preserve raw files, track status, and generate extracted representations.

Relevant plan sections:

- Section 5.2 Document Upload
- Section 5.3 Document Processing
- Section 9.1 Raw Layer
- Section 9.2 Extracted Layer
- Section 20.3 Document APIs
- Section 20.4 Processing APIs
- Section 21.1 Upload Document Use Case
- Section 21.2 Extract Document Use Case
- Section 24 Processing Status Model

Implementation checklist:

- [x] Define document domain entities and statuses:
  - [x] `uploaded`
  - [x] `extracting`
  - [x] `extracted`
  - [x] `generating_wiki`
  - [x] `wiki_ready`
  - [x] `indexing`
  - [x] `ready`
  - [x] `failed`
- [x] Define storage port.
- [x] Implement local storage adapter for Docker development.
- [x] Add S3/MinIO-compatible storage adapter boundary.
- [x] Define parser port.
- [x] Implement TXT parser.
- [x] Implement Markdown parser.
- [x] Implement PDF parser.
- [x] Implement DOCX parser.
- [x] Preserve document metadata:
  - [x] filename
  - [x] file type
  - [x] checksum
  - [x] page number where available
  - [x] section heading where available
- [x] Store raw files under a user/workspace/document path.
- [x] Store extracted JSON representation separately.
- [x] Implement upload use case.
- [x] Implement extraction use case.
- [x] Implement processing status transitions.
- [x] Implement document APIs:
  - [x] `POST /api/workspaces/{workspace_id}/documents`
  - [x] `GET /api/workspaces/{workspace_id}/documents`
  - [x] `GET /api/documents/{document_id}`
  - [x] `DELETE /api/documents/{document_id}`
  - [x] `POST /api/documents/{document_id}/process`
  - [x] `GET /api/documents/{document_id}/status`

Testing checklist:

- [x] Unit test file type validation.
- [x] Unit/API test unsupported file rejection.
- [x] Unit/API test raw storage path generation.
- [x] Unit/API test TXT extraction.
- [x] Unit test Markdown extraction.
- [x] Unit test PDF extraction with sample PDF.
- [x] Unit test DOCX extraction with sample DOCX.
- [x] API test document upload creates document record.
- [x] API test upload enforces workspace access.
- [x] API test processing updates status.
- [x] Integration test extracted files are written to storage.
- [x] Error test failed extraction marks document `failed`.

Phase 3 test notes:

```text
2026-05-23:
- Backend integration flow uploaded and processed `agreement.txt`.
- Docker E2E uploaded and processed `voice-policy.txt`; document status reached `ready`.
- PDF and DOCX parsers are implemented.

2026-05-24:
- Added parser tests for Markdown/TXT headings, DOCX paragraphs/tables, and PDF parsing.
- Added API tests for unsupported file rejection and private raw storage path shape.
- Added failed extraction API test; invalid PDF processing returns consistent `500` and document status becomes `failed`.
- Backend tests passed: `31 passed`.
```

---

## Phase 4 - Wiki Generation, Chunking, and Index Projection

Goal: convert extracted documents into wiki pages, chunk wiki/raw content, and build a rebuildable retrieval index.

Relevant plan sections:

- Section 5.4 Wiki Generation
- Section 5.5 RAG Search
- Section 9.3 Wiki Layer
- Section 9.4 Index Projection Layer
- Section 11 Retrieval Strategy
- Section 12 Chunking Strategy
- Section 19 Qdrant Collection Design
- Section 21.3 Generate Wiki Use Case
- Section 21.4 Build Index Use Case

Implementation checklist:

- [x] Define wiki domain entities:
  - [x] `WikiPage`
  - [x] `WikiGraph`
  - [x] wiki links
  - [x] backlinks
- [x] Define chunk domain entities:
  - [x] wiki section chunks
  - [x] raw source chunks
  - [x] table chunks
- [x] Define wiki generator port.
- [x] Implement deterministic local wiki generator fallback.
- [x] Add OpenRouter-backed wiki generator adapter boundary.
- [x] Generate topic pages from extracted documents.
- [x] Generate `INDEX.md`.
- [x] Generate `_backlinks.json`.
- [x] Generate `_absorb_log.json`.
- [x] Persist wiki pages in Postgres.
- [x] Persist wiki files in storage.
- [x] Implement markdown heading-based wiki chunking.
- [x] Implement raw document chunking by page, heading, paragraph, and table where available.
- [x] Implement table-to-text conversion format.
- [x] Define embeddings port.
- [x] Implement local deterministic embedding fallback for Docker development.
- [x] Add provider-ready embedding adapter boundary.
- [x] Define vector search port.
- [x] Implement Qdrant vector adapter.
- [x] Create `wikitics_chunks` Qdrant collection.
- [x] Upsert chunks with payload metadata:
  - [x] `user_id`
  - [x] `workspace_id`
  - [x] `document_id`
  - [x] `wiki_page_id`
  - [x] `source_type`
  - [x] `title`
  - [x] `heading`
  - [x] `path`
  - [x] `page_number`
  - [x] `content_preview`
- [x] Persist chunk metadata in Postgres.
- [x] Ensure indexes are rebuildable from canonical data.

Testing checklist:

- [x] Unit test wiki page generation.
- [x] Unit test `INDEX.md` generation.
- [x] Unit test backlinks generation.
- [x] Unit test absorb log generation.
- [x] Unit test wiki heading chunking.
- [x] Unit test raw chunking.
- [x] Unit test table chunking.
- [x] Unit test embedding vector dimensions.
- [x] Integration test Qdrant collection creation.
- [x] Integration test Qdrant upsert.
- [x] Integration test Qdrant search with required `user_id` and `workspace_id` filters.
- [x] Security test unfiltered vector search is not exposed through app use cases.
- [x] Rebuild test deletes and rebuilds index from stored documents/wiki.

Phase 4 test notes:

```text
2026-05-23:
- Docker E2E created Qdrant collection `wikitics_chunks`.
- Qdrant collection check showed status `green` and stored points.
- Backend unit tests cover wiki and raw chunking.

2026-05-24:
- Added `POST /api/workspaces/{workspace_id}/index/rebuild`.
- Integration flow now rebuilds the index from stored extracted documents/wiki and verifies rebuilt chunks.
- DOCX tables are preserved as extracted table metadata and indexed as raw table chunks.
- Added wiki generator, table chunking, and embedding dimension tests.
- Added `WikiGraph`/`WikiLink` domain objects and OpenRouter wiki generator adapter boundary.
- Added HTTP embedding adapter boundary with local fallback.
```

---

## Phase 5 - Text Question Answering and Citations

Goal: implement wiki-first hybrid retrieval and cited answer generation from uploaded documents.

Relevant plan sections:

- Section 5.6 Question Answering
- Section 10 Why Wiki + RAG + Raw Sources
- Section 11 Retrieval Strategy
- Section 20.6 Question Answering APIs
- Section 21.5 Ask Question Use Case
- Section 23 Prompting Strategy
- Section 26.4 Prompt Injection Protection

Implementation checklist:

- [x] Define retrieval result and context pack domain objects.
- [x] Implement question normalization.
- [x] Implement wiki vector search.
- [x] Implement title/heading keyword search.
- [x] Implement backlink expansion.
- [x] Implement raw source chunk retrieval for source proof.
- [x] Implement reranking strategy.
- [x] Implement compact context pack builder.
- [x] Add prompt injection protection rule:
  - [x] document content is treated as data, not instruction.
- [x] Define LLM port.
- [x] Implement local extractive answer fallback for Docker development.
- [x] Implement OpenRouter LLM adapter.
- [x] Implement conversation repository.
- [x] Store user questions.
- [x] Store assistant answers.
- [x] Store citations.
- [x] Implement Q&A APIs:
  - [x] `POST /api/workspaces/{workspace_id}/ask`
  - [x] `POST /api/workspaces/{workspace_id}/retrieval/search`
  - [x] `GET /api/conversations/{conversation_id}`
- [x] Return answer with citations and retrieved context.
- [x] Return "documents do not provide enough information" when context is insufficient.

Testing checklist:

- [x] Unit test context pack formatting.
- [x] Unit test insufficient context behavior.
- [x] Unit test prompt injection text is not treated as instruction.
- [x] Unit/API test citations are produced from raw chunks.
- [x] API test ask endpoint with indexed sample document.
- [x] API test retrieval filters by workspace and user.
- [x] API test document filter narrows retrieval.
- [x] API test conversation messages are persisted.
- [x] End-to-end test:
  - [x] upload sample document
  - [x] process document
  - [x] generate wiki
  - [x] build index
  - [x] ask question
  - [x] receive cited answer

Phase 5 test notes:

```text
2026-05-23:
- Backend integration test covered upload -> process -> ask -> cited answer.
- Docker E2E returned text answer with citations from uploaded documents.
- Retrieval code rejects vector searches missing `user_id` and `workspace_id`.

2026-05-24:
- Added workspace conversation listing API and frontend conversation history.
- Backend integration flow verifies persisted conversations after Q&A.
- Added context-pack tests for insufficient context, citation de-duplication, and the document-content-as-data prompt injection rule.
- Added question normalization, backlink expansion from linked documents, lightweight reranking, and document-filtered retrieval tests.
```

---

## Phase 6 - React Frontend for Upload, Wiki, Chat, and Citations

Goal: build the usable web application for document management and text Q&A.

Relevant plan sections:

- Section 7.1 Frontend
- Section 17 Frontend Architecture
- Section 20 API Design
- Section 29.1 MVP 1 - Text Q&A

Implementation checklist:

- [x] Set up React app with Tailwind CSS.
- [x] Add API client service.
- [x] Add auth state management.
- [x] Add routes:
  - [x] `/login`
  - [x] `/dashboard`
  - [x] `/workspaces/:workspaceId/documents`
  - [x] `/workspaces/:workspaceId/wiki`
  - [x] `/workspaces/:workspaceId/ask`
  - [x] `/workspaces/:workspaceId/conversations/:conversationId`
  - [x] `/settings`
- [x] Build login/register UI.
- [x] Build dashboard UI.
- [x] Build workspace selector UI.
- [x] Build document upload UI.
- [x] Build document processing status UI.
- [x] Build wiki browser UI.
- [x] Build text chat UI.
- [x] Build citation display UI.
- [x] Build conversation history UI.
- [x] Ensure UI is dense, operational, and not a marketing landing page.
- [x] Ensure responsive layouts do not overlap text or controls.

Testing checklist:

- [x] Frontend lint passes.
- [x] Frontend type check passes.
- [x] Frontend build passes.
- [x] Component test upload form behavior.
- [x] Component test chat question submission.
- [x] Component test citations render correctly.
- [x] Browser smoke test login/dashboard/documents/chat routes.
- [x] Browser smoke test mobile viewport.
- [x] Docker Compose frontend connects to backend API.

Phase 6 test notes:

```text
2026-05-23:
- `npm run build` passed.
- Playwright loaded `http://localhost:5173` and showed the login screen.
- Browser console smoke test reported 0 errors after favicon/autocomplete fixes.

2026-05-24:
- Added frontend source viewer, index rebuild control, conversation history, voice session end control, and health/metrics operations panel.
- `npm run lint` passed.
- `npm run build` passed.
- Playwright smoke loaded `http://127.0.0.1:5174/` at desktop and 390px mobile widths with 0 console errors.
- Added route navigation for dashboard, workspace documents/wiki/ask/conversations, conversation detail, and settings.
- Added Vitest + Testing Library component tests for upload, chat submission, and citation rendering.
- `npm run test` passed.
- Docker-served route smoke passed for `/settings` and workspace ask route at desktop/mobile widths with 0 console errors.
```

---

## Phase 7 - Voice Sessions, LiveKit Path, Sarvam STT/TTS, and Agent Worker

Goal: implement the voice interaction path so users can ask questions by voice and hear responses.

Relevant plan sections:

- Section 5.7 Voice Interaction
- Section 13 Voice Architecture with LiveKit
- Section 16 Agent Worker Folder Structure
- Section 20.7 Voice APIs
- Section 21.6 Create Voice Session Use Case
- Section 29.2 MVP 2 - Voice Q&A

Implementation checklist:

- [x] Define voice session domain entity.
- [x] Define STT port.
- [x] Define TTS port.
- [x] Define LiveKit voice adapter boundary.
- [x] Implement voice session use case.
- [x] Implement LiveKit token generation adapter.
- [x] Implement voice APIs:
  - [x] `POST /api/workspaces/{workspace_id}/voice/session`
  - [x] `POST /api/voice/session/{session_id}/end`
  - [x] `GET /api/voice/session/{session_id}`
- [x] Create agent worker service.
- [x] Implement FastAPI RAG client in agent worker.
- [x] Implement Sarvam STT adapter.
- [x] Implement Sarvam TTS adapter.
- [x] Implement OpenRouter streaming LLM adapter boundary.
- [x] Implement local/mock voice adapter fallback for Docker development.
- [x] Implement voice agent flow:
  - [x] receive transcript or audio input
  - [x] call FastAPI RAG endpoint
  - [x] generate answer text
  - [x] synthesize TTS response
  - [x] publish or expose response
- [x] Build frontend voice session UI.
- [x] Connect frontend to voice session creation API.
- [x] Display transcript, answer text, and citations during voice session.

Testing checklist:

- [x] Unit test LiveKit room name generation.
- [x] Unit test LiveKit token adapter with test config.
- [x] Unit/API test voice session lifecycle.
- [x] Unit test Sarvam STT adapter with mocked HTTP response.
- [x] Unit test Sarvam TTS adapter with mocked HTTP response.
- [x] Unit test agent worker RAG client.
- [x] API test create voice session.
- [x] API test end voice session.
- [x] API test voice session access isolation.
- [x] Agent worker smoke test starts in Docker.
- [x] Voice flow test with mocked transcript:
  - [x] transcript received
  - [x] RAG endpoint called
  - [x] answer generated
  - [x] TTS response produced
- [x] Frontend voice UI build and browser smoke test.

Phase 7 test notes:

```text
2026-05-23:
- Docker stack includes `livekit/livekit-server:v1.8`.
- Docker E2E created a voice session and called `/api/voice/session/{session_id}/ask`.
- Voice transcript answer returned citations and `audio_bytes > 0`.

2026-05-24:
- Added mocked Sarvam STT/TTS adapter tests and LiveKit token claim test.
- API integration flow creates a voice session, asks with a mocked transcript, verifies TTS bytes, and ends the session.
- API integration flow verifies cross-user voice session access is rejected.
- Added streaming LLM boundary method and agent-worker transcript/RAG/TTS test.
```

---

## Phase 8 - Reliability, Observability, Retries, and Production Readiness

Goal: harden the MVP around retries, security, observability, and repeatable Docker operation.

Relevant plan sections:

- Section 6 Non-Functional Requirements
- Section 24 Processing Status Model
- Section 25 Error Handling
- Section 26 Security Design
- Section 27 Observability
- Section 31 Deployment Plan
- Section 32 Important Engineering Rules

Implementation checklist:

- [x] Add background job structure for document pipeline stages.
- [x] Add retry support for:
  - [x] extraction
  - [x] wiki generation
  - [x] embedding generation
  - [x] Qdrant indexing
  - [x] LLM calls
  - [x] STT calls
  - [x] TTS calls
- [x] Add structured JSON logs.
- [x] Add request IDs.
- [x] Add health endpoints:
  - [x] backend
  - [x] database
  - [x] storage
- [x] Add metrics placeholders for:
  - [x] upload count
  - [x] processing failures
  - [x] extraction time
  - [x] wiki generation time
  - [x] embedding time
  - [x] Qdrant search latency
  - [x] LLM response latency
  - [x] STT latency
  - [x] TTS latency
  - [x] end-to-end voice latency
- [x] Add error response consistency.
- [x] Enforce MIME/file extension validation.
- [x] Enforce workspace filtering in all document, wiki, retrieval, conversation, and voice paths.
- [x] Add index rebuild command or API.
- [x] Add source viewer route/API if not already covered.
- [x] Document Docker setup and environment variables.

Testing checklist:

- [x] Unit test retry policy.
- [x] Unit test health response shape.
- [x] API test health endpoints.
- [x] API test consistent error responses.
- [x] Security test workspace isolation across all major APIs.
- [x] Security test no raw file public exposure path exists.
- [x] Security test retrieval requires `user_id` and `workspace_id` filters.
- [x] Integration test index rebuild.
- [x] Docker Compose full stack starts cleanly from a fresh checkout.
- [x] Docker Compose full stack restarts cleanly.

Phase 8 test notes:

```text
2026-05-23:
- Full Docker Compose stack starts and restarts cleanly.
- Only the `wikitics` Compose project is running after cleanup.
- Remaining production hardening: async retries, request IDs, metrics, index rebuild endpoint, and deeper provider mocks.

2026-05-24:
- Added reusable retry helper tests.
- Added request-context middleware with request IDs and JSON metric counters/timings.
- Added `/health/details` for database and storage probes.
- Added `/metrics/json` counters/timings endpoint.
- Added source viewer and index rebuild APIs.
- Backend tests passed: `25 passed`.
- Docker Desktop was started with `open -a Docker`.
- `docker compose up -d --build` passed.
- Verified no non-Wikitics containers are running.
- Docker E2E passed: register, workspace, upload, process, source, wiki, ask, conversations, index rebuild, voice transcript ask, end voice session, health, and metrics.
- Fixed index rebuild against Postgres by detaching old citation `chunk_id` references before deleting/recreating chunks.
- Added ignored local `.env` provider configuration for OpenRouter and Sarvam keys.
- Updated Compose to pass OpenRouter/Sarvam provider settings into backend and agent-worker.
- Verified backend and agent-worker containers see provider keys as set without printing secret values.
- Added provider-call fallbacks so OpenRouter/Sarvam outages do not break Q&A or voice.
- Provider-enabled Docker API flow passed: upload, process, text Q&A with citations, voice transcript Q&A, and TTS output.
```

---

## Final End-to-End Acceptance

Goal: prove the full success criteria from the plan.

Acceptance checklist:

- [x] Stop old containers.
- [x] Build all Docker images.
- [x] Start Docker Compose stack.
- [x] Register a user.
- [x] Create or use a workspace.
- [x] Upload at least one supported document.
- [x] Confirm raw document is stored privately.
- [x] Process the document.
- [x] Confirm extracted representation exists.
- [x] Confirm wiki pages are generated.
- [x] Confirm `INDEX.md`, `_backlinks.json`, and `_absorb_log.json` exist.
- [x] Confirm chunks are stored in Postgres.
- [x] Confirm vectors are stored in Qdrant.
- [x] Ask a text question.
- [x] Confirm answer is grounded in uploaded document context.
- [x] Confirm citations are returned.
- [x] Start a voice session.
- [x] Ask a question through the voice path or mocked voice transcript.
- [x] Confirm voice path retrieves context from FastAPI RAG.
- [x] Confirm answer text and TTS output path are produced.
- [x] Confirm frontend displays document status, wiki, answers, and citations.
- [x] Confirm no cross-workspace data leakage.

Final test notes:

```text
2026-05-23 Docker E2E:
- Register/login path worked.
- Uploaded `voice-policy.txt`.
- Processing returned status `ready`.
- Qdrant indexed chunks.
- Text Q&A returned citations.
- Voice transcript Q&A returned citations and TTS bytes.
- LiveKit token generation was verified against the dev LiveKit key/secret.
- Only Wikitics containers are running.

2026-05-24 Docker E2E:
- Docker Desktop started successfully.
- Only Wikitics containers are running.
- Uploaded `voice-policy.txt`.
- Processing returned status `ready` with 6 chunks.
- Source viewer API returned extracted pages and chunks.
- Text Q&A returned citations.
- Index rebuild returned 6 rebuilt chunks.
- Voice transcript Q&A returned citations and 417 TTS bytes.
- `/health/details` returned `status: ok`.
- Provider-enabled run verified `.env` OpenRouter/Sarvam wiring; voice transcript Q&A returned 591324 TTS bytes.
```

---

## Current Status

- Phase 0 is complete.
- Phase 1 is complete.
- Phases 2 through 8 are implemented against the current checklist.
- Broader hardening completed: repository/domain boundaries, wiki graph/link entities, provider adapter boundaries, retrieval filtering/reranking/backlink expansion, routes, component tests, error consistency, background job structure, provider env wiring, and Docker validation.
- Latest local verification passed on 2026-05-24:
  - `PYTHONPATH=backend backend/.venv/bin/pytest` -> `56 passed`.
  - `npm run lint` -> passed.
  - `npm run test` -> passed.
  - `npm run build` -> passed.
  - Playwright login/mobile smoke -> passed with 0 console errors.
- Latest Docker verification passed on 2026-05-24:
  - `docker compose up -d --build backend` -> passed.
  - Docker API E2E -> passed.
  - Provider-enabled Docker API E2E -> passed.
  - Voice latency benchmark passed: text stream `1.69s`, voice stream `3.77s`, voice TTS first byte `0.43s`, and first audio from voice start `1.55s`.
  - Docker-served frontend smoke at `http://localhost:5173` desktop/mobile -> passed with 0 console errors.
- Current app URLs:
  - Frontend: `http://localhost:5173`
  - Backend API docs: `http://localhost:8000/docs`
  - Qdrant: `http://localhost:6333/dashboard`
  - MinIO: `http://localhost:9001`
