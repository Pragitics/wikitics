# Frontend Chat And Voice Polish Plan

## Phase Checklist

- [x] Phase 1: Load persisted conversation history into the chat surface.
- [x] Phase 2: Make RAG answers short and conversational.
- [x] Phase 3: Use the full main panel for chat messages.
- [x] Phase 4: Move the voice/chat toggle below the top bar with rounded corners and no overlap.
- [x] Phase 5: Remove transcript/message display from voice mode.
- [x] Phase 6: Replace chat composer with a rounded multiline input and inline send button.
- [x] Phase 7: Style user messages with `#384959`; render assistant text without a bubble background.
- [x] Phase 8: Apply the `#384959` and white palette to mic, workspace list, background, and controls.
- [x] Phase 9: Round workspace name input and remove logout button border.
- [x] Phase 10: Run tests, rebuild Docker, and smoke test.
- [x] Phase 11: Add hover workspace options menu with delete action.

## UI Rules

- Keep implementation details hidden.
- The chat screen uses the full main panel.
- The composer stays at the bottom and grows when text wraps.
- The voice screen only shows the mic and listening state, not transcript bubbles.
- Use `#384959` as the primary color.
- Workspace rows expose destructive actions only through the hover/focus `...` menu.

## Verification

- [x] Frontend lint: `npm run lint`
- [x] Frontend tests: `npm run test` (`10 passed`)
- [x] Frontend production build: `npm run build`
- [x] Backend tests: `PYTHONPATH=backend backend/.venv/bin/pytest` (`56 passed`)
- [x] Docker rebuild: `docker compose up -d --build`
- [x] Docker health: `http://localhost:8000/health` and `http://localhost:5173`
- [x] Softrate DOCX smoke: uploaded `Softrate Workspace document .docx`, processed `158` chunks, created `1` wiki page, stored conversations, and answered from the uploaded document.
- [x] Browser smoke: verified voice screen hides transcript, chat history loads, toggle sits below top bar, composer grows within the viewport, and console has no errors.
- [x] Workspace delete menu tests: backend workspace cleanup integration, frontend sidebar menu behavior, full frontend lint/test/build, and full backend test suite passed.
- [x] Browser smoke: running Docker frontend shows the workspace `...` menu and its Delete action; console has no warnings or errors.
