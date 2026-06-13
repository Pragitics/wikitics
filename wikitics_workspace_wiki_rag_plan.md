# Wikitics Workspace Wiki And RAG Evolution Plan

Source of truth:

- `wikitics_detailed_technical_plan.md`
- Current Wikitics implementation in `backend/`, `frontend/`, and Docker Compose
- UI reference: Minimals level-based navigation bar, https://minimals.cc/components/extra/navigation-bar
- Reference architecture: Obsidian Vault Pipeline, https://github.com/fakechris/obsidian_vault_pipeline

## Product Model

Wikitics should use this model:

```text
User
  Workspaces
    Documents
    Workspace Wiki
    Wiki-first RAG Index
    Conversations
```

Each workspace is one private knowledge base. Users can create multiple workspaces, upload multiple documents into each workspace, and start multiple conversations inside that same workspace.

Conversations should not own documents. Conversations should only reference the active workspace knowledge base.

## Current State

- Multiple workspaces are supported.
- Multiple documents per workspace are supported.
- Text and voice Q&A are scoped by `user_id` and `workspace_id`.
- Conversations are stored per workspace and can be continued by `conversation_id`.
- If no `conversation_id` is passed, backend creates a new conversation.
- RAG currently retrieves from both raw document chunks and wiki chunks.
- Target direction is wiki-first retrieval: store raw/extracted source for provenance and rebuilds, but embed the LLM-maintained wiki/index/backlink layer as the primary RAG corpus.
- Wiki pages are generated during document processing.
- The current wiki pipeline is still document-centric.
- Wiki pages can be listed/read, but cannot be manually edited through an API/UI yet.
- The workspace index can be rebuilt, but there is not yet a fine-grained re-embed flow for one edited wiki page.
- Conversation history is stored but is not yet included in the LLM prompt.

## Target Architecture

```text
Workspace
  raw/
    uploaded files
    extracted text
    OCR output

  wiki/
    articles/
      concept pages
    index/
      workspace summaries
      maps
      backlinks
    absorb logs
    revisions

  rag/
    wiki chunks
    wiki index chunks
    backlink/concept-map chunks
    embeddings

  conversations/
    message history
    rolling memory summary
```

Raw documents remain the archival source of truth. The LLM-generated workspace wiki is the primary operating knowledge layer. RAG should primarily index wiki pages, wiki index pages, backlinks, summaries, and concept maps so the agent can quickly traverse the workspace knowledge base.

Raw extracted/OCR text should still be stored, but it does not need to be embedded by default. It should be available for audit, re-absorb, provenance checks, and emergency/full rebuilds.

The wiki maintenance loop should be autonomous. The LLM should create, edit, merge, lint, and repair the workspace wiki when new documents arrive or when a conversation reveals a missing concept. Human approval is not part of the normal path. The system should instead rely on provenance, confidence gates, audit logs, versioning, rollback, and automatic re-embedding.

## Autonomous Runtime Model

Wikitics should adapt the useful staged shape from Obsidian Vault Pipeline while keeping the product simpler:

```text
Ingest -> Interpret -> Absorb -> Normalize -> Derive -> Serve
```

Stage responsibilities:

- `Ingest`: store uploaded raw file, checksum, user/workspace/document identity.
- `Interpret`: extract/OCR text, tables, headings, metadata.
- `Absorb`: LLM proposes wiki page creates/updates, backlinks, index changes, and source provenance.
- `Normalize`: automatically merge aliases, resolve duplicate pages, apply confidence gates, version changed wiki pages.
- `Derive`: rebuild wiki-first RAG projections from changed wiki pages, indexes, backlinks, and maps.
- `Serve`: voice/chat answer using wiki-first RAG plus conversation memory.

Only raw source, wiki canonical state, revisions, provenance, and audit logs are durable truth. RAG vectors are projections and can always be deleted/rebuilt.

## UX Direction

Use a level-based navigation structure inspired by Minimals navigation.

Suggested navigation:

```text
Workspaces
  Softrate
    Chat
    Documents
    Wiki
    Conversations
    Settings
  Another Workspace
    Chat
    Documents
    Wiki
    Conversations
    Settings
```

Primary user flow:

```text
Create workspace -> Upload documents -> Wait for Ready -> Start voice/chat
```

The main UI should stay minimal. Implementation details like embeddings, Qdrant, chunks, extraction, OCR, and wiki generation should be hidden behind simple user-facing states.

## Phase 1 - Workspace And Conversation UX

Goal: make the product model explicit in the frontend.

Status: in progress. The workspace hierarchy, active-workspace conversations, first-document upload, conversation-area upload, and drag/drop upload slice is implemented and tested. The sidebar has been simplified to `Upload documents`, `New chat`, and conversation rows. Wiki and Settings navigation views remain pending.

Implementation checklist:

- [x] Add `New chat` inside each workspace.
- [x] Show a draft `New chat` row immediately when the user starts a fresh chat.
- [x] Keep recent conversations scoped to the active workspace.
- [x] Clicking a conversation loads its messages.
- [x] Starting voice can either create a new conversation or attach to the selected conversation.
- [x] Add document upload from the active conversation screen.
- [x] Enable whole-screen document drag/drop for the active workspace.
- [x] Reuse the same upload/prepare/ready processing stage for first upload and later document adds.
- [x] Add level-based sidebar navigation:
  - [x] Workspace list
  - [x] Active workspace children
  - [x] Upload documents
  - [ ] Wiki
  - [ ] Settings
- [x] Keep top bar focused on the active workspace name.
- [x] Keep upload and chat/voice screen minimal.
- [x] Remove the top workspace bar and move logout into the sidebar.
- [x] Keep long conversation names clipped inside the sidebar row.

Testing checklist:

- [ ] Create two workspaces and verify switching changes documents/conversations.
- [ ] Create multiple conversations in one workspace.
- [x] Verify each conversation loads its own history.
- [x] Verify a voice session attaches to the intended conversation.
- [ ] Verify no conversation from workspace A appears in workspace B.
- [x] Verify the first-document flow shows upload processing before a conversation starts.
- [x] Verify adding another document from the active conversation screen triggers upload and processing.
- [x] Verify whole-screen document drop triggers upload and processing before the first conversation starts.

Phase 1 test notes:

- Frontend unit/integration tests: `npm run test` passed, 14 tests.
- Frontend type check: `npm run lint` passed.
- Frontend production build: `npm run build` passed.
- Docker smoke: `docker compose up -d --build frontend` completed, Wikitics services are running, browser check passed with no console errors.
- Live document smoke: `Softrate Workspace document .docx` uploaded through Docker API, processed to `ready`, and produced 158 chunks.
- UI polish smoke: sidebar shows `Upload documents` and `New chat`, no `Chat` or `Conversations` child item, new draft chat row appears, top bar is removed, and logout is in the sidebar.

## Phase 2 - Bounded Conversation Memory

Goal: make follow-up questions work without sending unlimited history.

Status: implemented. The QA path now loads bounded recent turns for an existing conversation, uses them to improve retrieval for follow-up questions, includes conversation memory in the LLM context pack, and keeps document/wiki context as the source of truth. Conversation titles are stored and generated after the answer path using `OPENROUTER_TITLE_MODEL` with deterministic fallback. Durable rolling summaries are handled by Phase 3.

Current issue:

- The app stores chat history and sends bounded conversation context to the LLM for continued conversations.
- The LLM sees current question, retrieved document/wiki context, recent turns, and rolling summary memory when available.

Target prompt inputs:

```text
current question
workspace RAG context
conversation memory summary
last N turns
voice/text style instructions
```

Recommended limits:

- Voice: rolling summary plus last 2 turns.
- Text: rolling summary plus last 4 to 6 turns.
- Voice history budget: about 1500 to 2500 characters.
- Text history budget: about 4000 to 6000 characters.

Implementation checklist:

- [x] Add conversation memory summary fields to conversations.
- [x] Fetch bounded recent messages before LLM call.
- [x] Add memory summary and recent turns to context pack.
  - [x] Durable memory summary
  - [x] Recent turns
- [x] Keep document/wiki RAG context higher priority than memory.
- [x] Add prompt rule: document content is source of truth; memory only resolves conversation references.
- [x] Use bounded recent turns to improve retrieval for follow-up questions.
- [x] Return conversation-memory size in `context_stats` for observability.
- [x] Store generated conversation titles separately from the first user message.
- [x] Use a configurable cheap title model through `OPENROUTER_TITLE_MODEL`.

Testing checklist:

- [x] Ask a follow-up like "what about the second one?" and verify bounded recent turns are loaded.
- [x] Ask a document-grounded question after long chat history and verify RAG still dominates.
- [ ] Verify voice prompt remains below target context size.
- [x] Verify text prompt memory is bounded by character budget.

Phase 2A test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/unit/test_context.py backend/tests/integration/test_api_flow.py::test_follow_up_question_uses_bounded_conversation_context` passed, 8 tests.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 65 tests.
- Live follow-up smoke: after asking "Which software services are mentioned?", a second turn "What about the second one?" returned `conversation_memory_characters=468`.
- Title generation tests: cheap-model title adapter and stored conversation title behavior are covered in backend tests.

## Phase 3 - Async Conversation Summarizer

Goal: summarize long conversation history without adding live response latency.

Status: implemented.

Flow:

```text
User asks
  -> answer uses existing summary + last turns + RAG
  -> save messages
  -> if conversation is long, enqueue summarizer job
  -> summarizer updates stored memory summary
  -> next turn uses updated summary
```

The summarizer should run after the answer. It must not block voice response.

Implementation checklist:

- [x] Add summary trigger thresholds:
  - [x] message count threshold
  - [x] character/token threshold
  - [x] stale summary threshold
- [x] Add background job for conversation summarization.
- [x] Store `memory_summary`, `memory_updated_at`, and `memory_message_cursor`.
- [x] Summarizer prompt should capture:
  - [x] user goals
  - [x] unresolved references
  - [x] preferences
  - [x] terminology
  - [x] decisions already made
- [x] Summarizer must not invent document facts.

Testing checklist:

- [x] Long conversation triggers summarization after answer.
- [x] Current answer latency does not wait for summarizer.
- [x] Next answer includes updated summary.
- [x] Summary does not override retrieved document evidence.

Phase 3 test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/unit/test_context.py backend/tests/unit/test_adapters.py::test_openrouter_summary_uses_configured_cheap_model backend/tests/integration/test_api_flow.py::test_async_conversation_summary_is_stored_and_used_next_turn backend/tests/integration/test_api_flow.py::test_conversation_summary_job_does_not_block_current_answer` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 65 tests.
- Docker smoke: `docker compose up -d --build backend agent-worker` completed, `/health` returned `ok`, and Postgres `conversations` has `memory_summary`, `memory_updated_at`, and `memory_message_cursor`.
- The summarizer uses `OPENROUTER_SUMMARY_MODEL`, defaults to `openai/gpt-4o-mini`, and falls back to the local deterministic summarizer when no API key is configured.
- The summary is injected into prompts as `Memory summary` beside bounded `Recent turns`; prompt rules keep uploaded document/wiki context as the source of truth.

## Phase 4 - Regional Code-Mixed Voice Style

Goal: voice answers should sound natural for Indian users, not formal textbook regional language.

Status: implemented.

Decision:

- Do this in the main answer LLM call.
- Do not add a second LLM conversion call before TTS.
- TTS should speak the final answer text directly.

Prompt behavior:

```text
For voice replies, answer in the user's language style.
Use natural Indian code-mixing when the user uses it.
Keep common technical/business terms in English.
Do not translate words like invoice, software, app, website, service, payment, dashboard, login, upload, workspace.
Avoid formal textbook translation.
Keep it short and conversational.
```

Examples:

```text
Haan, document mein software development, app development aur website services mention hain.
```

```text
Aama, indha document-la software development, app development, website services mention pannirukku.
```

Implementation checklist:

- [x] Detect voice language/style from STT transcript.
- [x] Add voice style instruction to context pack.
- [x] Keep technical glossary terms in English.
- [x] Add workspace/request preference:
  - [x] auto
  - [x] English
  - [x] Hinglish
  - [x] Tanglish
  - [x] other supported regional mix
- [x] Keep voice answer shaping after LLM output.

Testing checklist:

- [x] Hinglish transcript produces natural Hinglish answer.
- [x] Tamil-English transcript produces natural code-mixed answer.
- [x] Fully English transcript stays English.
- [x] Technical terms stay in English.
- [x] Voice latency does not add an extra LLM call.

Phase 4 test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/unit/test_context.py backend/tests/integration/test_api_flow.py::test_workspace_voice_style_preference_guides_voice_prompt` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 70 tests.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Docker smoke: `docker compose up -d --build backend frontend agent-worker` completed, `/health` returned `ok`, and Postgres `workspaces` has `voice_style_preference`.
- The voice prompt now detects English, Hinglish, Tanglish, and generic Indic regional mix locally, and workspace/request overrides can force a style without adding another LLM call.

## Phase 5 - Autonomous Workspace Wiki Absorb Pipeline

Goal: adding a new document later should automatically update the workspace wiki instead of treating every document as an isolated wiki.

Status: in progress. The deterministic workspace absorb path is implemented: later documents are compared against existing workspace wiki pages by path/title, same-concept pages are updated with sourced evidence, new concepts create new pages, workspace `INDEX.md` and backlinks are rewritten from all pages, per-document absorb logs are stored, and changed wiki/document chunks are replaced before re-indexing. LLM-backed planning, confidence gates, versioned patching, and quarantine remain pending.

Current issue:

- Wiki generation is per-document.
- Workspace `INDEX.md` and backlinks are written during document processing.
- There is no proper merge step that compares the new document to existing workspace wiki pages.

Target flow when a document is processed:

```text
extract document
OCR if needed
generate candidate wiki updates
load existing workspace wiki index/pages
decide create/update/skip for each concept
write changed wiki pages
update backlinks and index
write absorb log
re-embed only changed wiki pages, wiki indexes, and backlinks
```

Absorb decisions:

- `create_page`: new concept or topic.
- `update_page`: existing concept gets new evidence.
- `append_evidence`: existing high-confidence page needs a safe sourced addition.
- `skip`: duplicate or low-value content.
- `auto_repair`: conflicting/stale data can be resolved from provenance.
- `quarantine`: conflicting data cannot be safely resolved automatically; exclude from RAG and log for audit, but do not block the rest of the pipeline.

Implementation checklist:

- [x] Add workspace wiki read model:
  - [x] pages
  - [x] index
  - [x] backlinks
  - [x] absorb logs
- [ ] Add `WikiAbsorbService`.
- [ ] Add LLM-backed absorb planner with deterministic fallback.
- [x] Compare candidate document concepts against existing wiki pages.
- [x] Track changed page IDs.
- [x] Write absorb log for every document.
- [x] Preserve raw document source links on wiki pages.
- [ ] Protect existing high-confidence pages from blind overwrite by using versioned patches.
- [x] Store source provenance for wiki claims so raw documents can be audited without embedding all raw text.
- [x] Automatically promote high-confidence wiki changes.
- [ ] Automatically quarantine low-confidence/conflicting claims instead of requiring human approval.

Testing checklist:

- [x] Upload document A and generate wiki.
- [x] Upload document B with same concept and verify existing page updates.
- [x] Upload document C with new concept and verify new page is created.
- [x] Verify `INDEX.md` includes all workspace concepts.
- [x] Verify backlinks update after absorb.
- [x] Verify absorb log records create/update decisions.
- [ ] Verify absorb log records skip/repair/quarantine decisions.

Phase 5 test notes:

- Backend targeted test: `backend/.venv/bin/pytest backend/tests/integration/test_api_flow.py::test_later_documents_absorb_into_workspace_wiki_and_logs` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Docker smoke: `docker compose up -d --build backend frontend agent-worker` completed, `/health` returned `ok`, and Postgres has `wiki_absorb_logs`.
- This phase now exposes `GET /api/workspaces/{workspace_id}/wiki/absorb-logs` for read-only absorb audit data.

## Phase 6 - Autonomous Wiki Editing And Versioning

Goal: the LLM can edit the workspace wiki and RAG immediately reflects the change. Manual edit APIs may exist for admin/debug, but normal operation is autonomous.

Status: in progress. Admin/debug wiki edit, revision, revert, and page reindex APIs are implemented. Edits save the old page as a revision, update stored markdown, rebuild the workspace index, replace wiki page chunks/vectors, and allow rollback by revision. Autonomous LLM maintenance jobs, edit validation, backlink rebuild on rename, and generated-edit rollback remain pending.

API design:

```text
GET    /api/workspaces/{workspace_id}/wiki/pages/{page_id}
PATCH  /api/workspaces/{workspace_id}/wiki/pages/{page_id}
GET    /api/workspaces/{workspace_id}/wiki/pages/{page_id}/revisions
POST   /api/workspaces/{workspace_id}/wiki/pages/{page_id}/revert
POST   /api/workspaces/{workspace_id}/wiki/pages/{page_id}/reindex
POST   /api/workspaces/{workspace_id}/wiki/maintain
```

Patch payload:

```json
{
  "title": "Service Overview",
  "content": "# Service Overview\n...",
  "edit_note": "Clarified service categories"
}
```

Implementation checklist:

- [x] Add wiki page update API.
- [x] Add wiki revision table.
- [x] Save old content before every edit.
- [x] Store edit actor: `llm`, `system`, or `admin`.
- [x] Store `edited_by`, `edited_at`, and `edit_note`.
- [ ] Store source document provenance for manual/generated edits.
- [x] Update stored markdown file.
- [x] Rebuild wiki index if title/content changes.
- [ ] Rebuild backlinks if title/path/content changes.
- [x] Re-index edited page into RAG.
- [x] Add autonomous maintenance endpoint/job for create/edit/merge/lint/repair actions.
- [ ] Add automatic rollback path if a generated edit fails validation.

Testing checklist:

- [x] LLM maintenance job edits wiki page content.
- [x] Verify page read returns edited content.
- [x] Verify revision is created.
- [x] Ask a question that depends on edited text and verify RAG uses the edited wiki.
- [x] Revert a revision and verify RAG changes back after reindex.
- [x] Invalid generated edit falls back or is quarantined and does not enter RAG.

Phase 6 test notes:

- Backend targeted test: `backend/.venv/bin/pytest backend/tests/integration/test_api_flow.py::test_wiki_page_edit_revision_reindex_and_revert` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Docker smoke: `docker compose up -d --build backend frontend agent-worker` completed, `/health` returned `ok`, and Postgres has `wiki_revisions`.
- Implemented APIs: `PATCH /api/workspaces/{workspace_id}/wiki/pages/{page_id}`, `GET /api/workspaces/{workspace_id}/wiki/pages/{page_id}/revisions`, `POST /api/workspaces/{workspace_id}/wiki/pages/{page_id}/revert`, and `POST /api/workspaces/{workspace_id}/wiki/pages/{page_id}/reindex`.

## Phase 7 - Incremental Wiki-First RAG Re-Embedding

Goal: re-embed only changed wiki knowledge, not the entire workspace or all raw source text.

Status: implemented as wiki-only reindexing. Changed wiki pages, workspace index, and backlinks are reindexed incrementally. Raw documents remain in storage and extracted metadata for provenance and future absorb, but they are no longer chunked into RAG. Delete-document repair/quarantine is still a future hardening item.

Current full rebuild:

- Deletes workspace chunks and rebuilds wiki page, index, and backlink chunks only.

Target behavior:

- RAG primarily stores wiki-derived chunks.
- Raw extracted text stays in storage/database for provenance and future wiki absorb.
- Raw chunks should not be part of the retrieval corpus.

Target incremental flow:

For new document:

```text
extract/OCR raw text
absorb into workspace wiki
embed changed wiki pages
embed changed wiki index/backlink summaries
replace changed wiki vectors
```

For edited wiki page:

```text
delete chunks/vectors where wiki_page_id = page_id
chunk edited page
embed chunks
upsert vectors
save chunks
```

For deleted document:

```text
mark affected wiki pages stale
remove, repair, or quarantine claims sourced only from deleted document
re-embed changed wiki pages/indexes
```

Implementation checklist:

- [x] Add vector delete by `wiki_page_id`.
- [x] Add chunk replacement by `wiki_page_id`.
- [x] Add chunk type for wiki index/backlink/concept-map entries.
- [x] Add `reindex_wiki_pages(page_ids)`.
- [x] Add `reindex_wiki_index(workspace_id)`.
- [x] Make raw document embedding optional behind a setting/admin path.
- [x] Keep full rebuild API as recovery/admin path.

Testing checklist:

- [x] Edit one wiki page and verify only that page's wiki chunks are replaced.
- [x] Upload one new document and verify changed wiki/index vectors are replaced.
- [ ] Delete one document and verify affected wiki pages are marked stale, repaired, or quarantined.
- [x] Full rebuild from stored raw documents still reconstructs the wiki/RAG state.

Phase 7 test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/integration/test_api_flow.py::test_wiki_page_edit_revision_reindex_and_revert backend/tests/integration/test_api_flow.py::test_incremental_wiki_reindex_projection_and_maintenance_logs` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Added `POST /api/workspaces/{workspace_id}/wiki/reindex` for multi-page and index/backlink projection reindexing.
- Added `wiki_index` and `wiki_backlinks` RAG chunk projections.

## Phase 8 - Autonomous Wiki Maintenance Loop

Goal: LLM continuously maintains the workspace wiki without human approval, while the UI exposes auditability and rollback.

Status: implemented for the guarded maintenance path. Document processing can use the configured OpenRouter wiki model to create/absorb workspace wiki pages, then refresh wiki-first RAG. The maintenance endpoint validates wiki pages, quarantines prompt-injection content, uses the configured OpenRouter wiki model to synthesize duplicate-page merges when provider keys are configured, falls back to deterministic repair when needed, repairs markdown lint issues, versions changes, rebuilds backlinks/indexes, and reindexes changed wiki projections.

User-facing flow:

```text
Document uploaded
Preparing
Wiki maintained
RAG refreshed
Ready
```

Implementation checklist:

- [x] Add autonomous wiki maintenance endpoint.
- [ ] Add autonomous wiki maintenance worker.
- [x] Trigger wiki generation/absorb and RAG refresh after document process.
- [ ] Trigger maintenance when conversation answer detects missing wiki coverage.
- [ ] Trigger maintenance on scheduled lint/staleness checks.
- [ ] Validate generated wiki edits before writing:
  - [x] required source provenance exists
  - [ ] no unsupported claim without source link
  - [x] no prompt-injection instructions copied into wiki
  - [x] page schema/frontmatter is valid
  - [x] backlinks/index are valid
- [x] Commit valid autonomous maintenance updates automatically.
- [x] Re-embed changed wiki projections automatically.
- [x] Expose read-only maintenance log API.
- [x] Expose rollback, not approval, for admins.

Testing checklist:

- [x] Low-risk new page is automatically committed during LLM document absorb when provider keys are configured.
- [x] Existing page update is automatically absorbed during later document processing.
- [x] Duplicate wiki pages are merged, versioned, and reindexed by autonomous maintenance.
- [x] Wiki lint issues are repaired, versioned, and reindexed by autonomous maintenance.
- [x] Prompt-injection content is quarantined and logged.
- [x] Valid maintenance rebuild updates wiki index projections in RAG.
- [x] Rollback restores previous wiki content and RAG projection.

Phase 8 test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/integration/test_api_flow.py::test_incremental_wiki_reindex_projection_and_maintenance_logs backend/tests/integration/test_api_flow.py::test_wiki_maintenance_quarantines_prompt_injection_text backend/tests/integration/test_api_flow.py::test_wiki_maintenance_merges_duplicates_repairs_lint_and_reindexes` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- OpenRouter wiki generator wiring test: `backend/.venv/bin/pytest backend/tests/unit/test_adapters.py::test_openrouter_wiki_generator_uses_configured_model` passed.
- OpenRouter wiki maintenance wiring test: `backend/.venv/bin/pytest backend/tests/unit/test_adapters.py::test_openrouter_wiki_maintenance_merge_uses_configured_model` passed.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Implemented APIs: `POST /api/workspaces/{workspace_id}/wiki/maintain` and `GET /api/workspaces/{workspace_id}/wiki/maintenance-logs`.

## Phase 9 - Wiki-First Retrieval Policy

Goal: RAG should primarily operate on the workspace wiki, with raw documents used for provenance and rebuilds.

Status: implemented as strict wiki-first retrieval and prompting. Wiki, wiki index, and backlink chunks are the only retrieval corpus. Raw documents are retained only as stored evidence and provenance inputs for wiki absorb, maintenance, and audit.

Retrieval policy:

- Retrieve wiki pages for conceptual understanding and factual answers.
- Retrieve wiki index/backlink/concept-map chunks for fast traversal.
- Prefer current workspace only.
- Use document filters only when the user explicitly selects documents.
- Keep raw source references attached to wiki claims for audit.
- If a wiki claim is uncertain or challenged, verify against stored raw/extracted source before updating the wiki.

Prompt policy:

```text
Use workspace wiki as the operating knowledge base.
Use wiki source references for provenance.
If a fact is missing from the wiki, say the workspace wiki does not contain enough information.
Conversation memory helps resolve references but cannot introduce facts.
```

Testing checklist:

- [x] Question answered from wiki summary/index when broad.
- [x] Question answered from wiki claim/source reference when specific.
- [x] Edited wiki page affects conceptual answer.
- [ ] Wiki answer can show source references back to raw document/page metadata.
- [x] Cross-workspace retrieval remains impossible.

Phase 9 test notes:

- Backend targeted tests: `backend/.venv/bin/pytest backend/tests/unit/test_context.py backend/tests/integration/test_api_flow.py::test_incremental_wiki_reindex_projection_and_maintenance_logs` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- Frontend checks: `npm run test`, `npm run lint`, and `npm run build` passed.
- Context builder now treats `wiki`, `wiki_index`, and `wiki_backlinks` as wiki knowledge and includes the workspace-wiki source-of-truth prompt policy.

## Phase 10 - End-To-End Acceptance

Acceptance scenario:

```text
Create workspace
Upload document A
Process into raw, wiki, and RAG
Start conversation A
Ask voice question
Start conversation B
Ask different chat question
Upload document B later
Absorb document B into existing workspace wiki
Incrementally re-embed changed wiki pages and wiki index/backlink chunks
LLM document absorb autonomously creates or updates one wiki page
Re-index edited wiki page automatically
Ask follow-up question using conversation memory
Answer uses workspace wiki/RAG and natural voice style
```

Acceptance checklist:

- [x] Multiple workspaces work independently.
- [x] Multiple documents in one workspace work together.
- [x] Multiple conversations in one workspace work independently.
- [x] Conversation memory works for follow-ups.
- [x] Async summarizer does not affect voice latency.
- [x] Regional code-mixed voice style happens in the main LLM call.
- [x] New document can be added later and absorbed into workspace wiki.
- [x] LLM autonomously creates and updates wiki pages during document absorb.
- [x] LLM/deterministic maintenance autonomously merges, lints, and repairs wiki pages outside the document absorb path.
- [x] Admin/autonomous edit API updates wiki-first RAG.
- [x] Incremental re-embedding works.
- [x] Full rebuild from stored raw documents remains available as recovery.
- [x] All APIs enforce `user_id` and `workspace_id`.

Phase 10 test notes:

- Backend acceptance test: `backend/.venv/bin/pytest backend/tests/integration/test_api_flow.py::test_workspace_wiki_rag_end_to_end_acceptance` passed.
- Backend full suite: `backend/.venv/bin/pytest backend/tests` passed, 79 tests.
- Docker smoke after Phase 7-10 implementation: `docker compose up -d --build backend frontend agent-worker` completed, `/health` returned `ok`, and Postgres has `wiki_maintenance_logs`.

## Recommended Build Order

1. Workspace/conversation UX cleanup with level-based navigation.
2. Bounded conversation memory in prompts.
3. Async conversation summarizer.
4. Regional code-mixed voice prompt style.
5. Autonomous wiki edit/version API and re-index one page.
6. Incremental vector deletion/replacement utilities.
7. Autonomous workspace wiki absorb pipeline for later document uploads.
8. Autonomous maintenance logs, validation, quarantine, and rollback UX.

This order improves the user experience quickly, then adds the deeper wiki/RAG mutation system safely.
