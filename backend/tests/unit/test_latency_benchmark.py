import json

from app.benchmarks.latency_benchmark import (
    Thresholds,
    parse_sse_events,
    summarize_text_stream,
    summarize_voice_stream,
    threshold_failures,
)


def test_parse_sse_events_reads_json_payloads():
    body = (
        'event: context_ready\n'
        'data: {"type":"context_ready","latency":{"embedding":0.01}}\n\n'
        'event: answer_delta\n'
        'data: {"type":"answer_delta","delta":"Hi"}\n\n'
        'event: final\n'
        f"data: {json.dumps({'answer': 'Hi', 'latency': {'llm_stream': 0.4}})}\n\n"
    )

    events = parse_sse_events(body)

    assert [event["type"] for event in events] == ["context_ready", "answer_delta", "final"]
    assert events[2]["answer"] == "Hi"


def test_benchmark_summaries_extract_latency_and_audio_stats():
    text_summary = summarize_text_stream(
        [
            {"type": "context_ready", "latency": {"embedding": 0.01}, "context_stats": {"result_count": 2}},
            {"type": "answer_delta", "delta": "Hi"},
            {"type": "final", "answer": "Hi there", "latency": {"llm_stream": 0.5}},
        ],
        0.9,
    )
    voice_summary = summarize_voice_stream(
        [
            {"type": "answer", "answer": "Hi"},
            {"type": "audio_start", "audio_mime": "audio/mpeg"},
            {"type": "audio_delta", "audio_bytes": 10},
            {
                "type": "final",
                "answer": "Hi there",
                "audio_bytes": 10,
                "voice_latency": {"tts_first_byte": 0.2, "qa": {"llm_response": 0.6}},
            },
        ],
        1.2,
    )

    assert text_summary["first_delta_event_index"] == 1
    assert text_summary["latency"]["llm_stream"] == 0.5
    assert voice_summary["first_audio_event_index"] == 2
    assert voice_summary["audio_bytes"] == 10
    assert voice_summary["voice_latency"]["tts_first_byte"] == 0.2


def test_threshold_failures_reports_exceeded_limits():
    summary = {
        "text_stream": {"wall_seconds": 1.5, "latency": {"llm_stream": 1.2}},
        "voice_stream": {
            "wall_seconds": 2.5,
            "voice_latency": {"tts_first_byte": 0.7, "qa": {"llm_response": 1.3}},
        },
    }

    failures = threshold_failures(
        summary,
        Thresholds(
            text_final_seconds=1.0,
            voice_final_seconds=2.0,
            voice_first_audio_seconds=0.5,
            llm_seconds=1.0,
        ),
    )

    assert len(failures) == 5
    assert failures[0].startswith("text wall time")
