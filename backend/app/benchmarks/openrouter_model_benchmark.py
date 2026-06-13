from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from urllib import request
from urllib.error import HTTPError

from app.benchmarks.latency_benchmark import BenchmarkClient, find_workspace_id

try:
    import certifi
except ImportError:  # pragma: no cover - fallback for minimal Python installs
    certifi = None


AUTO_MODEL_PREFERENCES = [
    "openai/gpt-4.1-mini",
    "google/gemini-2.5-flash",
    "google/gemini-2.5-flash-lite",
    "anthropic/claude-3.5-haiku",
    "meta-llama/llama-3.3-70b-instruct",
    "qwen/qwen-2.5-72b-instruct",
]


@dataclass(frozen=True)
class ModelThresholds:
    max_first_delta_seconds: float | None = None
    max_total_seconds: float | None = None
    min_quality_score: float | None = None


def build_voice_context(question: str, results: list[dict[str, Any]], max_sections: int = 6, chars_per_section: int = 700) -> str:
    if not results:
        return "No relevant context was found in the workspace wiki."
    lines = [f"User Question:\n{question}", "", "Relevant Wiki Context:"]
    for index, result in enumerate(results[:max_sections], start=1):
        payload = result.get("payload") or {}
        label = payload.get("path") or payload.get("filename") or payload.get("title") or result.get("source_type") or "source"
        content = str(result.get("content") or "")[:chars_per_section]
        lines.append(f"{index}. {label}\n{content}")
    lines.extend(
        [
            "",
            "Instructions:",
            "- Answer only from the document context.",
            "- Speak like a real-time voice assistant.",
            "- Use 1-2 short spoken sentences.",
            "- Adapt to intent: teach simply if the user wants to learn; answer directly for factual questions.",
            "- No markdown and no citations unless asked.",
        ]
    )
    return "\n".join(lines)


def build_openrouter_payload(model: str, question: str, context_pack: str, max_tokens: int = 120) -> dict[str, Any]:
    return {
        "model": model,
        "stream": True,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a low-latency voice assistant for a workspace wiki. "
                    "Use only the provided workspace wiki context. Keep the answer short, natural, and conversational."
                ),
            },
            {"role": "user", "content": f"Question: {question}\n\n{context_pack}"},
        ],
        "temperature": 0.25,
        "max_tokens": max_tokens,
    }


class OpenRouterBenchmarkClient:
    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.ssl_context = ssl.create_default_context(cafile=certifi.where()) if certifi else None

    def list_models(self) -> list[str]:
        req = request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            method="GET",
        )
        with request.urlopen(req, timeout=30, context=self.ssl_context) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [str(item["id"]) for item in payload.get("data", []) if item.get("id")]

    def stream_model(self, model: str, question: str, context_pack: str, max_tokens: int = 120) -> dict[str, Any]:
        payload = build_openrouter_payload(model, question, context_pack, max_tokens=max_tokens)
        started = perf_counter()
        first_delta_seconds = None
        deltas: list[str] = []
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=120, context=self.ssl_context) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    delta = parse_openrouter_delta(line)
                    if delta is None:
                        continue
                    if first_delta_seconds is None:
                        first_delta_seconds = perf_counter() - started
                    deltas.append(delta)
        except HTTPError as exc:
            return {
                "model": model,
                "ok": False,
                "error": exc.read().decode("utf-8", errors="replace")[:500],
                "status_code": exc.code,
            }
        except OSError as exc:
            return {"model": model, "ok": False, "error": str(exc)}

        total_seconds = perf_counter() - started
        answer = "".join(deltas).strip()
        return {
            "model": model,
            "ok": bool(answer),
            "answer": answer,
            "answer_chars": len(answer),
            "word_count": len(answer.split()),
            "first_delta_seconds": first_delta_seconds,
            "total_seconds": total_seconds,
        }


def parse_openrouter_delta(line: str) -> str | None:
    if not line.startswith("data:"):
        return None
    data = line.removeprefix("data:").strip()
    if data == "[DONE]":
        return None
    try:
        payload = json.loads(data)
    except ValueError:
        return None
    return payload.get("choices", [{}])[0].get("delta", {}).get("content") or None


def select_auto_models(available_models: list[str], limit: int) -> list[str]:
    available = set(available_models)
    selected = [model for model in AUTO_MODEL_PREFERENCES if model in available]
    if len(selected) < limit:
        for model in available_models:
            lowered = model.lower()
            if model in selected:
                continue
            if any(token in lowered for token in ("flash", "mini", "haiku", "llama", "qwen")):
                selected.append(model)
            if len(selected) >= limit:
                break
    return selected[:limit]


def score_model_result(result: dict[str, Any], context_pack: str) -> dict[str, Any]:
    if not result.get("ok"):
        return {**result, "quality_score": 0, "grounding_hits": 0}
    answer = str(result.get("answer") or "")
    word_count = len(answer.split())
    context_words = important_words(context_pack)
    answer_words = important_words(answer)
    grounding_hits = len(context_words.intersection(answer_words))
    score = 0
    if answer:
        score += 30
    if 4 <= word_count <= 45:
        score += 25
    elif word_count <= 65:
        score += 12
    if not re.search(r"[*#`]|\\n\\s*[-*]", answer):
        score += 15
    if grounding_hits >= 3:
        score += 20
    elif grounding_hits:
        score += 10
    if not re.search(r"insufficient|do not provide|can't find|cannot find", answer, re.I):
        score += 10
    return {**result, "quality_score": score, "grounding_hits": grounding_hits}


def important_words(text: str) -> set[str]:
    stopwords = {"about", "there", "their", "which", "would", "could", "should", "document", "context", "question"}
    return {
        word
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9]{4,}", text.lower())
        if word not in stopwords
    }


def threshold_failures(results: list[dict[str, Any]], thresholds: ModelThresholds) -> list[str]:
    failures: list[str] = []
    for result in results:
        if not result.get("ok"):
            failures.append(f"{result['model']} failed: {result.get('error', 'no answer')}")
            continue
        if thresholds.max_first_delta_seconds is not None and result.get("first_delta_seconds", 0) > thresholds.max_first_delta_seconds:
            failures.append(
                f"{result['model']} first delta {result['first_delta_seconds']:.3f}s exceeded {thresholds.max_first_delta_seconds:.3f}s"
            )
        if thresholds.max_total_seconds is not None and result.get("total_seconds", 0) > thresholds.max_total_seconds:
            failures.append(f"{result['model']} total {result['total_seconds']:.3f}s exceeded {thresholds.max_total_seconds:.3f}s")
        if thresholds.min_quality_score is not None and result.get("quality_score", 0) < thresholds.min_quality_score:
            failures.append(f"{result['model']} quality {result['quality_score']} below {thresholds.min_quality_score}")
    return failures


def recommend_model(results: list[dict[str, Any]]) -> str | None:
    successful = [result for result in results if result.get("ok")]
    if not successful:
        return None
    ranked = sorted(
        successful,
        key=lambda item: (
            -float(item.get("quality_score", 0)),
            float(item.get("first_delta_seconds") or 999),
            float(item.get("total_seconds") or 999),
        ),
    )
    return str(ranked[0]["model"])


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    app_client = BenchmarkClient(args.base_url, token=args.token)
    if not app_client.token:
        if not args.email or not args.password:
            raise RuntimeError("Provide either --token or both --email and --password")
        app_client.login(args.email, args.password)

    api_key = args.openrouter_api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required")

    workspace_id = args.workspace_id or find_workspace_id(app_client, args.workspace_name)
    search_results = app_client.post_json(
        f"/api/workspaces/{workspace_id}/retrieval/search",
        {"query": args.question},
    )
    context_pack = build_voice_context(args.question, search_results, max_sections=args.max_context_sections)
    openrouter = OpenRouterBenchmarkClient(api_key, args.openrouter_base_url)
    models = parse_models_arg(args.models)
    if models == ["auto"]:
        models = select_auto_models(openrouter.list_models(), args.auto_limit)
    if not models:
        raise RuntimeError("No models selected")

    results = [
        score_model_result(openrouter.stream_model(model, args.question, context_pack, max_tokens=args.max_tokens), context_pack)
        for model in models
    ]
    thresholds = ModelThresholds(
        max_first_delta_seconds=args.max_first_delta_seconds,
        max_total_seconds=args.max_total_seconds,
        min_quality_score=args.min_quality_score,
    )
    return {
        "workspace_id": workspace_id,
        "question": args.question,
        "context_characters": len(context_pack),
        "models": models,
        "results": results,
        "recommended_model": recommend_model(results),
        "threshold_failures": threshold_failures(results, thresholds),
    }


def parse_models_arg(value: str) -> list[str]:
    models = [model.strip() for model in value.split(",") if model.strip()]
    return models or ["auto"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Benchmark OpenRouter models for Wikitics voice-style answers.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token")
    parser.add_argument("--email")
    parser.add_argument("--password")
    parser.add_argument("--workspace-id")
    parser.add_argument("--workspace-name")
    parser.add_argument("--openrouter-api-key")
    parser.add_argument("--openrouter-base-url", default=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    parser.add_argument("--models", default=os.getenv("OPENROUTER_MODEL", "openai/gpt-4.1-mini"))
    parser.add_argument("--auto-limit", type=int, default=4)
    parser.add_argument("--question", default="In one short spoken sentence, what software services are mentioned?")
    parser.add_argument("--max-context-sections", type=int, default=6)
    parser.add_argument("--max-tokens", type=int, default=120)
    parser.add_argument("--max-first-delta-seconds", type=float)
    parser.add_argument("--max-total-seconds", type=float)
    parser.add_argument("--min-quality-score", type=float)
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
