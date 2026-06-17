# Wikitics Core Latency And Accuracy Plan

## Source Of Truth

- `wikitics_detailed_technical_plan.md`
- Current implementation in `backend/`, `frontend/`, `agent-worker/`, and Docker Compose.

## Reference Findings

- LiveKit recommends an STT-LLM-TTS pipeline as the production default when auditability and tool/RAG control matter, but latency must be reduced by overlapping stages and handling turn-taking/interruption well: https://docs.livekit.io/agents/models/pipelines/
- LiveKit turn handling supports interruption detection, false-interruption handling, and user/agent state events: https://docs.livekit.io/agents/logic/turns/
- OpenRouter chat completions support `stream: true`, which lets the app receive LLM deltas over HTTPS before the full answer is complete: https://openrouter.ai/docs/api-reference/chat-completion
- OpenRouter Models API exposes available model IDs and metadata for repeatable model selection/benchmarking: https://openrouter.ai/docs/api/api-reference/models/get-models
- Sarvam STT has a WebSocket streaming API with VAD signals and flush support for low-latency transcription, but it requires WAV or raw PCM audio for streaming: https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/speech-to-text/streaming-api
- Sarvam TTS has HTTP and WebSocket streaming. HTTP streaming returns binary audio chunks; WebSocket is better for voice agents because the connection stays warm across turns: https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/text-to-speech/streaming-api/http-stream
- Sarvam Document Intelligence can extract OCR, structure, tables, and Markdown/HTML from PDFs/images, with a 10-page job limit per PDF/ZIP: https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/document-intelligence/overview

## Phase Checklist

- [x] Phase 1: Add latency observability across voice and QA stages.
- [x] Phase 2: Add bounded context profiles so voice sends less context to the LLM than text mode.
- [x] Phase 3: Make voice answers short, spoken, and intent-adaptive.
- [x] Phase 4: Add OpenRouter HTTPS streaming support and a streaming ask endpoint.
- [x] Phase 5: Add manual barge-in so clicking the mic during speech interrupts the current response without ending the session.
- [x] Phase 5a: Switch default Sarvam TTS payload from WAV to MP3 and return codec-specific MIME type to reduce audio payload size.
- [x] Phase 6: Move browser capture toward streaming PCM/WAV frames for Sarvam streaming STT.
- [x] Phase 7: Stream TTS audio chunks to playback instead of waiting for full base64 audio.
- [x] Phase 8: Add automatic barge-in using VAD while the agent is speaking.
- [x] Phase 9: Benchmark OpenRouter models for voice latency and answer quality.
- [x] Phase 10: Add PDF OCR fallback through Sarvam Document Intelligence or a local OCR adapter, then store OCR output in extracted document storage.
- [x] Phase 10a: Detect scanned/empty-text PDF pages and persist `ocr_required_pages` metadata for the OCR fallback.
- [x] Phase 11: Add a repeatable latency benchmark command and acceptance thresholds.
- [x] Phase 12: Use warm Sarvam WebSocket TTS for voice streaming with HTTP fallback and transport tracing.
- [x] Phase 13: Start TTS from partial streamed LLM sentence chunks before the final answer event.

## Current Implemented Changes

- Voice responses now include `voice_latency` with STT, TTS, QA stage timings, and total observed timing.
- QA responses now include `latency` and `context_stats`.
- QA retrieval now records embedding, vector search, keyword search, backlink expansion, rerank, context build, and LLM timings.
- Voice mode uses a smaller context budget: fewer retrieved results and fewer characters per section.
- `POST /api/workspaces/{workspace_id}/ask/stream` streams `context_ready`, `answer_delta`, and `final` SSE events.
- OpenRouter adapter now supports actual streaming deltas when the provider supports streaming.
- Frontend mic click during `speaking` now interrupts current audio/speech and resumes the same voice conversation.
- Sarvam TTS now defaults to MP3 (`audio/mpeg`) instead of WAV to reduce response payload size.
- `POST /api/voice/session/{session_id}/audio/stream` streams `transcript`, `answer`, `audio_start`, `audio_delta`, and `final` SSE events.
- Frontend voice calls now consume streamed voice SSE events and play streamed TTS chunks with MediaSource when supported, with Blob playback fallback.
- `WebSocket /api/voice/session/{session_id}/stt/stream` proxies browser PCM16 audio chunks to Sarvam streaming STT with provider credentials kept server-side.
- Browser voice capture now converts mic frames to 16 kHz little-endian PCM16 and flushes the STT buffer at detected turn end, then sends the transcript into the streamed answer/TTS path.
- Frontend voice playback now monitors mic energy during agent speech and automatically interrupts playback after sustained user speech, then resumes listening in the same session.
- Browser mic capture now requests echo cancellation, noise suppression, and auto gain control to reduce false barge-ins from speaker playback.
- `scripts/benchmark_latency.py` measures text streaming and voice transcript streaming wall time, stage latency, context size, first audio timing, audio bytes, and optional threshold failures.
- `scripts/benchmark_openrouter_models.py` compares OpenRouter models on retrieved workspace context, measuring first-token latency, total streaming time, concise voice-answer quality, and grounding hits.
- Default OpenRouter model is `openai/gpt-4.1-mini` for chat answers and wiki generation. `google/gemini-2.5-flash` had measured lower first-token latency in the earlier benchmark, but GPT-4.1 mini is preferred for the production workflow because instruction following, wiki editing consistency, and output-token cost matter more for Wikitics.
- PDF parsing now stores `ocr_required_pages`, `page_text_lengths`, and `ocr_status` metadata so scanned PDFs are visible to the processing pipeline.
- PDF processing now calls a Sarvam Document Intelligence OCR adapter for scanned/empty-text pages, merges OCR text back into extracted pages, and stores raw OCR output at `extracted/{document_id}/ocr.json`.
- Document source responses include extracted metadata, so OCR status and stored OCR output paths are visible to API consumers without showing implementation details in the frontend.
- Sarvam TTS streaming now prefers a persistent WebSocket connection (`/text-to-speech/ws`) configured once per backend process, sends text/flush messages per turn, decodes base64 audio chunks, and falls back to the existing HTTP stream if the WebSocket path fails.
- Voice latency output now includes `tts_transport`, so benchmarks prove whether a turn used `websocket`, `http_stream`, or a fallback path.
- Voice answers are shaped before TTS: direct voice answers are constrained to one short spoken sentence, while learning/explanation intent can use two short sentences.
- Voice transcript streaming now consumes the LLM stream on a producer thread using its own DB session, so history persistence and `llm_stream` timing are not blocked by TTS synthesis.
- Voice TTS starts as soon as a sentence-ready streamed answer segment is available, while the final answer still gets saved and emitted with citations.
- Voice latency now separates provider first-byte time (`tts_first_byte`) from perceived route timing (`first_audio_from_voice_start`).

## Verification Snapshot

- Backend tests: `PYTHONPATH=backend backend/.venv/bin/pytest` -> `56 passed`.
- Frontend lint/test/build: `npm run lint`, `npm run test` (`10 passed`), and `npm run build` passed.
- Docker rebuild: `docker compose up -d --build backend frontend` passed.
- Health checks: `http://localhost:8000/health` and `http://localhost:5173` passed.
- Latency benchmark command passed against the Softrate workspace with thresholds: text stream `2.21s`, voice stream `5.65s`, voice TTS first byte `0.44s`, and no threshold failures.
- OpenRouter model benchmark passed against the Softrate workspace with three models. `google/gemini-2.5-flash` was recommended with quality score `100`, first token `1.16s`, and total stream `1.34s`; previous default `openai/gpt-4.1-mini` scored `100`, first token `2.04s`, and total stream `2.70s`.
- Earlier app latency benchmarks passed after switching to `google/gemini-2.5-flash`; re-run the latency benchmark after the `openai/gpt-4.1-mini` default change before setting production SLOs.
- After switching Sarvam TTS to WebSocket-first streaming and shaping voice answers, the live app benchmark passed with thresholds: text stream `1.46s`, voice stream `5.29s`, voice QA LLM response `1.20s`, voice TTS first byte `0.50s`, TTS stream `4.06s`, and `tts_transport: websocket`.
- After partial LLM-to-TTS streaming with the threaded producer, the live app benchmark passed with thresholds: text stream `1.69s`, voice stream `3.77s`, voice QA LLM stream `1.13s`, first audio from voice start `1.55s`, voice TTS first byte `0.43s`, TTS stream `2.63s`, and `tts_transport: websocket`.
- Browser smoke after Phase 13 verified the Docker frontend loads the Softrate workspace, persisted recent conversations render, conversation `...` exposes Delete, the chat surface loads the selected history, and console warnings/errors are clear.
- Browser smoke verified the Softrate workspace loads, recent-chat options expose Delete, and no console warnings/errors are present.
- Live text QA smoke on the Softrate workspace returned stage latency. Retrieval was milliseconds; LLM response was the dominant text-stage cost.
- Live HTTPS streaming smoke returned `context_ready`, many `answer_delta` events, and `final`.
- Live transcript-to-voice streaming smoke returned `answer`, `audio_start`, `audio_delta`, and `final` from the Softrate workspace.
- Backend streamed voice API test verified the new SSE voice response shape with `audio_delta` chunks before `answer`, final metadata, transport tracing, and `llm_stream` not being inflated by TTS work.
- Backend WebSocket test verified the app STT bridge accepts PCM16 audio messages, emits VAD events, and returns a transcript on `flush`.
- Backend OCR tests verified Document Intelligence payload decoding, ZIP JSON output decoding, OCR metadata extraction, scanned-PDF OCR merge/storage, and indexing of OCR text.
- Backend workspace cleanup test exercises deletion after document, conversation, and voice-session data exist, and the service cleanup path removes workspace-owned database rows, vector entries, and storage prefixes.
- Frontend test coverage verifies PCM16 little-endian encoding for streamed browser audio frames.
- Frontend test coverage verifies sustained-speech barge-in detection and the echo-cancellation mic constraints.
- Frontend test coverage verifies the workspace row hover/focus options menu can delete the active workspace and select the next workspace.
- Live voice transcript smoke returned `voice_latency`; current observed bottleneck is Sarvam TTS streaming duration, around `3.2s` for a short MP3 answer after a first byte around `0.44s`.
- Current observed bottleneck after WebSocket TTS is still total Sarvam synthesis/playback duration, around `4.1s` for a short MP3 answer after first byte around `0.5s`.
- Current observed bottleneck after partial TTS overlap is still Sarvam synthesis/playback duration, but route wall time dropped to about `3.8s` for the benchmark voice answer.

## Next Implementation Targets

- Browser-level voice smoke with real mic permissions, playback, VAD interruption, and chat-history persistence in the Docker frontend.
- Tune Sarvam TTS voice/bitrate/chunk thresholds if the browser playback smoke still sounds broken or slow.
