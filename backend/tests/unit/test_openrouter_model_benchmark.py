import json

from app.benchmarks.openrouter_model_benchmark import (
    build_voice_context,
    parse_models_arg,
    parse_openrouter_delta,
    recommend_model,
    score_model_result,
    select_auto_models,
    threshold_failures,
    ModelThresholds,
)


def test_build_voice_context_uses_retrieved_sections():
    context = build_voice_context(
        "What services are mentioned?",
        [
            {
                "source_type": "raw",
                "content": "Software development and website design are available.",
                "payload": {"filename": "services.docx"},
            }
        ],
    )

    assert "services.docx" in context
    assert "Software development" in context
    assert "1-2 short spoken sentences" in context


def test_parse_openrouter_delta_reads_streaming_content():
    line = "data: " + json.dumps({"choices": [{"delta": {"content": "hello"}}]})

    assert parse_openrouter_delta(line) == "hello"
    assert parse_openrouter_delta("data: [DONE]") is None
    assert parse_openrouter_delta(": ping") is None


def test_auto_model_selection_prefers_fast_model_families():
    selected = select_auto_models(
        [
            "slow/frontier",
            "google/gemini-2.5-flash",
            "openai/gpt-4.1-mini",
            "vendor/other",
        ],
        limit=2,
    )

    assert selected == ["openai/gpt-4.1-mini", "google/gemini-2.5-flash"]


def test_score_and_recommend_model_prefers_quality_then_latency():
    context = "Software development website development app development digital marketing"
    slow_good = score_model_result(
        {
            "model": "slow-good",
            "ok": True,
            "answer": "They mention software development, website development, app development, and digital marketing.",
            "first_delta_seconds": 0.7,
            "total_seconds": 2.0,
        },
        context,
    )
    fast_bad = score_model_result(
        {
            "model": "fast-bad",
            "ok": True,
            "answer": "I cannot find that in the documents.",
            "first_delta_seconds": 0.2,
            "total_seconds": 0.8,
        },
        context,
    )

    assert slow_good["quality_score"] > fast_bad["quality_score"]
    assert recommend_model([fast_bad, slow_good]) == "slow-good"


def test_model_threshold_failures():
    failures = threshold_failures(
        [
            {
                "model": "model-a",
                "ok": True,
                "first_delta_seconds": 1.4,
                "total_seconds": 3.2,
                "quality_score": 55,
            }
        ],
        ModelThresholds(max_first_delta_seconds=1.0, max_total_seconds=3.0, min_quality_score=60),
    )

    assert len(failures) == 3


def test_parse_models_arg_supports_csv_and_auto():
    assert parse_models_arg("a,b") == ["a", "b"]
    assert parse_models_arg("") == ["auto"]
