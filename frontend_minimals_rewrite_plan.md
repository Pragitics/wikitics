# Wikitics Frontend Rewrite Plan

Source references:

- Minimal customized stepper: https://minimals.cc/components/mui/stepper#customized-stepper
- Minimal vertical navigation bar: https://minimals.cc/components/extra/navigation-bar#vertical
- Minimal single file upload: https://minimals.cc/components/extra/upload#upload-single-file
- Minimal scrollbar: https://minimals.cc/components/extra/scrollbar
- Minimal sign-in page: https://minimals.cc/auth/amplify/sign-in?returnTo=%2Fdashboard
- Minimal dashboard layout: https://minimals.cc/components/extra/layout
- Minimal form wizard: https://minimals.cc/components/extra/form-wizard
- Minimal animate components: https://minimals.cc/components/extra/animate
- Minimal Tailwind docs: https://docs.minimals.cc/tailwind/

## Goal

Rewrite the frontend into a minimal voice-first document agent interface.

The user should not see system internals such as extraction, wiki generation, vector indexing, Qdrant, chunks, citations internals, health checks, or metrics. The UI should feel like:

```text
Create workspace -> Upload documents -> Wait for simple progress -> Talk to the agent
```

The user can switch between voice and chat, but voice is the primary mode.

## Allowed Component References Only

Use only the component patterns listed above:

- Sign-in page for authentication.
- Dashboard layout for app shell.
- Vertical navigation bar for workspace navigation.
- Single file upload for document upload.
- Customized stepper or form wizard for upload progress.
- Scrollbar for chat/history areas.
- Animate for smooth screen transitions and mic state changes.

Do not reuse the current dense dashboard panels, source viewer, metrics cards, backend health panels, detailed wiki panels, chunk views, or implementation-heavy operational UI.

If the licensed Minimal component source is not available in this repo, build local equivalents that match these referenced component behaviors and visual style without copying proprietary source.

## Primary User Flow

### 1. Login

Route:

```text
/login
```

Behavior:

- Minimal sign-in page.
- Email/password login.
- Secondary register action may be available, but the page should stay simple.
- On success, route to the workspace dashboard.

APIs:

- `POST /api/auth/login`
- `POST /api/auth/register`
- `GET /api/auth/me`

### 2. Workspace Shell

Routes:

```text
/dashboard
/workspaces/:workspaceId
```

Layout:

- Minimal dashboard layout.
- Vertical nav on the left.
- Top bar shows only the active workspace name.
- Nav item: `Workspaces`.
- Optional compact account/logout control.

Workspace actions:

- List workspaces.
- Create workspace.
- Select workspace.
- Delete workspace from the row `...` menu.

APIs:

- `GET /api/workspaces`
- `POST /api/workspaces`
- `GET /api/workspaces/{workspace_id}`
- `DELETE /api/workspaces/{workspace_id}`

### 3. Document Upload Center

Route:

```text
/workspaces/:workspaceId
```

Initial center screen:

- One single-file upload component in the center.
- No side panels.
- No wiki/source/chunk/citation implementation details.
- Keep the screen quiet and focused.

Accepted files:

- `.pdf`
- `.docx`
- `.txt`
- `.md`
- `.markdown`

APIs:

- `POST /api/workspaces/{workspace_id}/documents`
- `POST /api/documents/{document_id}/process`

### 4. Upload Progress

Use customized stepper or form wizard.

Do not expose implementation names like:

- extracting
- generating wiki
- indexing
- Qdrant
- chunks
- embeddings

User-facing progress labels:

```text
Uploading
Preparing
Ready
```

Internal mapping:

```text
uploading -> POST document upload
preparing -> POST document process
ready -> document status ready
failed -> simple retry/error state
```

The progress surface should be centered and minimal.

### 5. Agent Ready State

After upload/process is complete:

- Hide upload details.
- Show a large mic button in the center.
- Show a small mode toggle:

```text
Voice | Chat
```

Default mode:

```text
Voice
```

The mic button is the primary action.

### 6. Voice Interaction

Voice mode:

- Big centered mic button.
- On click, create or reuse a voice session.
- Browser speech recognition can capture transcript when available.
- Transcript is sent to backend voice endpoint.
- Agent response should be spoken through browser speech synthesis or returned audio/TTS path.
- Keep transcript and answer display minimal.

APIs:

- `POST /api/workspaces/{workspace_id}/voice/session`
- `POST /api/voice/session/{session_id}/ask`
- `POST /api/voice/session/{session_id}/end`

UI states:

```text
Idle
Listening
Thinking
Speaking
```

Use Minimal animate components for state transitions.

### 7. Chat Toggle

Chat mode:

- Show a minimal chat input.
- Show conversation messages in a scrollbar area.
- Do not show raw citations by default.
- If citations are needed, show a small "Sources" disclosure only after an answer.

APIs:

- `POST /api/workspaces/{workspace_id}/ask`
- `GET /api/workspaces/{workspace_id}/conversations`
- `GET /api/conversations/{conversation_id}`

## Screens

### Login Screen

Use:

- Minimal sign-in reference.
- No marketing content.
- No dashboard/sidebar.

### Workspace Screen

Use:

- Dashboard layout.
- Vertical nav.
- Top bar workspace name.
- Center upload/agent canvas.

### Upload Screen State

Use:

- Single file upload.
- Customized stepper/form wizard.

### Agent Screen State

Use:

- Big mic button.
- Voice/chat toggle.
- Scrollbar only for chat transcript/history.
- Animate for transitions.

## API Contract Summary

Auth:

```text
POST /api/auth/login
POST /api/auth/register
GET  /api/auth/me
```

Workspaces:

```text
GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{workspace_id}
```

Documents:

```text
POST /api/workspaces/{workspace_id}/documents
POST /api/documents/{document_id}/process
GET  /api/documents/{document_id}/status
```

Text agent:

```text
POST /api/workspaces/{workspace_id}/ask
GET  /api/workspaces/{workspace_id}/conversations
GET  /api/conversations/{conversation_id}
```

Voice agent:

```text
POST /api/workspaces/{workspace_id}/voice/session
POST /api/voice/session/{session_id}/ask
POST /api/voice/session/{session_id}/end
```

## State Model

Frontend app state:

```text
unauthenticated
authenticated-no-workspace
workspace-selected
upload-idle
uploading
preparing
agent-ready
voice-listening
agent-thinking
agent-speaking
chat-active
error
```

Do not expose backend stage names directly to users.

## Visual Direction

- Minimal.
- Spacious center canvas.
- No dense operational side panels.
- No source/chunk/wiki debug panels.
- No metrics/health in main product UI.
- Top bar text should be limited to workspace name.
- Use restrained colors and soft transitions.
- Mic button should be the strongest visual element after upload completes.

## Implementation Checklist

- [x] Remove current dense dashboard layout from `frontend/src/app/App.tsx`.
- [x] Add login screen matching Minimal sign-in reference.
- [x] Add dashboard shell matching Minimal layout reference.
- [x] Add vertical workspace nav.
- [x] Add workspace create/select flow.
- [x] Add top bar showing active workspace name.
- [x] Add center single-file upload view.
- [x] Add upload/preparing/ready progress stepper.
- [x] Hide extraction/wiki/indexing implementation details.
- [x] Add agent-ready view with large mic button.
- [x] Add voice/chat mode toggle.
- [x] Add voice session creation and transcript ask flow.
- [x] Add minimal chat mode.
- [x] Add scrollbar chat history.
- [x] Add animate transitions for upload-to-agent and voice states.
- [x] Keep API client compatible with existing backend endpoints.
- [x] Add frontend tests for login, workspace creation, upload progress, voice mode, and chat mode.
- [x] Run `npm run lint`.
- [x] Run `npm run test`.
- [x] Run `npm run build`.
- [x] Rebuild Docker frontend.
- [x] Browser smoke test desktop and mobile.

## Verification Log

- [x] `npm run lint`
- [x] `npm run test`
- [x] `npm run build`
- [x] `PYTHONPATH=backend backend/.venv/bin/pytest`
- [x] `docker compose up -d --build frontend`
- [x] Docker health check for frontend and backend
- [x] Browser smoke test on `http://localhost:5173`
- [x] Browser chat ask against uploaded workspace document
- [x] Mobile viewport smoke test

## Post-Rewrite Polish Checklist

- [x] Apply `#384959` and white-led color combo.
- [x] Keep page background and workspace navigation background aligned.
- [x] Remove visible `Idle` status pill from voice mode.
- [x] Replace browser speech-recognition dependency with recorded-audio voice requests.
- [x] Add browser VAD silence detection for utterance capture.
- [x] Change mic behavior to continuous conversation until stopped.
- [x] Normalize browser audio MIME types before Sarvam STT.
- [x] Add backend voice audio endpoint using Sarvam STT.
- [x] Set Sarvam STT explicitly to `saaras:v3`.
- [x] Set Sarvam TTS explicitly to `bulbul:v3`, `en-IN`, `shubh`.
- [x] Play Sarvam TTS audio in the browser instead of browser-generated speech when available.
- [x] Test `Softrate Workspace document .docx` upload and processing.
- [x] Test chat answer against `Softrate Workspace document .docx`.
- [x] Test voice-audio answer against `Softrate Workspace document .docx`.
