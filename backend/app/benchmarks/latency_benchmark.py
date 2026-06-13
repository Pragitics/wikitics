from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib import request
from urllib.error import HTTPError


@dataclass(frozen=True)
class Thresholds:
    text_final_seconds: float | None = None
    voice_final_seconds: float | None = None
    voice_first_audio_seconds: float | None = None
    llm_seconds: float | None = None


def parse_sse_events(body: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body.split("\n\n"):
        event_type = "message"
        data_lines: list[str] = []
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].strip())
        if not data_lines:
            continue
        payload = json.loads("\n".join(data_lines))
        payload.setdefault("type", event_type)
        events.append(payload)
    return events


def summarize_text_stream(events: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    first_delta_index = next((index for index, event in enumerate(events) if event.get("type") == "answer_delta"), None)
    final = next((event for event in reversed(events) if event.get("type") == "final"), {})
    context_ready = next((event for event in events if event.get("type") == "context_ready"), {})
    latency = final.get("latency") or {}
    return {
        "wall_seconds": wall_seconds,
        "event_count": len(events),
        "first_delta_event_index": first_delta_index,
        "answer_chars": len(str(final.get("answer") or "")),
        "latency": latency,
        "context_stats": final.get("context_stats") or context_ready.get("context_stats") or {},
    }


def summarize_voice_stream(events: list[dict[str, Any]], wall_seconds: float) -> dict[str, Any]:
    first_audio_index = next((index for index, event in enumerate(events) if event.get("type") == "audio_delta"), None)
    final = next((event for event in reversed(events) if event.get("type") == "final"), {})
    voice_latency = final.get("voice_latency") or {}
    return {
        "wall_seconds": wall_seconds,
        "event_count": len(events),
        "first_audio_event_index": first_audio_index,
        "answer_chars": len(str(final.get("answer") or "")),
        "audio_bytes": final.get("audio_bytes", 0),
        "voice_latency": voice_latency,
        "context_stats": final.get("context_stats") or {},
    }


def threshold_failures(summary: dict[str, Any], thresholds: Thresholds) -> list[str]:
    failures: list[str] = []
    text = summary.get("text_stream") or {}
    voice = summary.get("voice_stream") or {}
    if thresholds.text_final_seconds is not None and text.get("wall_seconds", 0) > thresholds.text_final_seconds:
        failures.append(f"text wall time {text['wall_seconds']:.3f}s exceeded {thresholds.text_final_seconds:.3f}s")
    if thresholds.voice_final_seconds is not None and voice.get("wall_seconds", 0) > thresholds.voice_final_seconds:
        failures.append(f"voice wall time {voice['wall_seconds']:.3f}s exceeded {thresholds.voice_final_seconds:.3f}s")
    if thresholds.voice_first_audio_seconds is not None:
        first_audio = ((voice.get("voice_latency") or {}).get("tts_first_byte"))
        if first_audio is not None and first_audio > thresholds.voice_first_audio_seconds:
            failures.append(f"voice TTS first byte {first_audio:.3f}s exceeded {thresholds.voice_first_audio_seconds:.3f}s")
    if thresholds.llm_seconds is not None:
        text_llm = (text.get("latency") or {}).get("llm_stream") or (text.get("latency") or {}).get("llm_response")
        voice_llm = (((voice.get("voice_latency") or {}).get("qa") or {}).get("llm_response"))
        if text_llm is not None and text_llm > thresholds.llm_seconds:
            failures.append(f"text LLM {text_llm:.3f}s exceeded {thresholds.llm_seconds:.3f}s")
        if voice_llm is not None and voice_llm > thresholds.llm_seconds:
            failures.append(f"voice LLM {voice_llm:.3f}s exceeded {thresholds.llm_seconds:.3f}s")
    return failures


class BenchmarkClient:
    def __init__(self, base_url: str, token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token

    def login(self, email: str, password: str) -> None:
        payload = self.post_json("/api/auth/login", {"email": email, "password": password})
        self.token = str(payload["access_token"])

    def post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        return json.loads(self.request("POST", path, payload=payload))

    def get_json(self, path: str) -> dict[str, Any] | list[dict[str, Any]]:
        return json.loads(self.request("GET", path))

    def post_sse(self, path: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], float]:
        started = perf_counter()
        body = self.request("POST", path, payload=payload)
        return parse_sse_events(body), perf_counter() - started

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> str:
        headers = {}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=120) as response:
                return response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    client = BenchmarkClient(args.base_url, token=args.token)
    if not client.token:
        if not args.email or not args.password:
            raise RuntimeError("Provide either --token or both --email and --password")
        client.login(args.email, args.password)

    workspace_id = args.workspace_id or find_workspace_id(client, args.workspace_name)
    text_events, text_wall = client.post_sse(
        f"/api/workspaces/{workspace_id}/ask/stream",
        {"question": args.text_question},
    )
    voice_session = client.post_json(f"/api/workspaces/{workspace_id}/voice/session", {})
    voice_events, voice_wall = client.post_sse(
        f"/api/voice/session/{voice_session['session_id']}/ask/stream",
        {"transcript": args.voice_transcript},
    )
    summary = {
        "base_url": args.base_url,
        "workspace_id": workspace_id,
        "text_stream": summarize_text_stream(text_events, text_wall),
        "voice_stream": summarize_voice_stream(voice_events, voice_wall),
    }
    thresholds = Thresholds(
        text_final_seconds=args.max_text_seconds,
        voice_final_seconds=args.max_voice_seconds,
        voice_first_audio_seconds=args.max_voice_first_audio_seconds,
        llm_seconds=args.max_llm_seconds,
    )
    failures = threshold_failures(summary, thresholds)
    summary["threshold_failures"] = failures
    return summary


def find_workspace_id(client: BenchmarkClient, workspace_name: str | None) -> str:
    workspaces = client.get_json("/api/workspaces")
    if not isinstance(workspaces, list) or not workspaces:
        raise RuntimeError("No workspaces available")
    if workspace_name:
        normalized = workspace_name.strip().lower()
        for workspace in workspaces:
            if str(workspace.get("name", "")).strip().lower() == normalized:
                return str(workspace["id"])
        raise RuntimeError(f"Workspace not found: {workspace_name}")
    return str(workspaces[0]["id"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark Wikitics text and voice streaming latency.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--workspace-id")
    parser.add_argument("--workspace-name")
    parser.add_argument(
        "--text-question",
        default="In one short sentence, what is this document mainly about?",
    )
    parser.add_argument(
        "--voice-transcript",
        default="In one short spoken sentence, what is this document mainly about?",
    )
    parser.add_argument("--max-text-seconds", type=float)
    parser.add_argument("--max-voice-seconds", type=float)
    parser.add_argument("--max-voice-first-audio-seconds", type=float)
    parser.add_argument("--max-llm-seconds", type=float)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        summary = run_benchmark(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True))
    return 1 if summary["threshold_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
