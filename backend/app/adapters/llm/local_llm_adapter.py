class LocalLLMAdapter:
    def answer(self, question: str, context_pack: str) -> str:
        if "No relevant context" in context_pack or not context_pack.strip():
            return "The workspace wiki does not provide enough information to answer this question."
        lines = [
            line.strip()
            for line in context_pack.splitlines()
            if line.strip() and not line.strip().endswith(":") and not line.strip().startswith("-")
        ]
        detailed = _needs_detailed_answer(question)
        evidence = " ".join(lines[:10 if detailed else 4])
        limit = 900 if detailed else 300
        if len(evidence) > limit:
            evidence = f"{evidence[: limit - 3].rstrip()}..."
        return (
            f"Based on the workspace wiki, {evidence}"
            if evidence
            else "The workspace wiki does not provide enough information to answer this question."
        )

    def title(self, messages: list[dict]) -> str:
        first_user = next((message.get("content", "") for message in messages if message.get("role") == "user"), "")
        return compact_title(first_user)

    def summarize_conversation(self, existing_summary: str, messages: list[dict]) -> str:
        user_texts = [_clean(message.get("content", "")) for message in messages if message.get("role") == "user"]
        assistant_texts = [_clean(message.get("content", "")) for message in messages if message.get("role") == "assistant"]
        goals = "; ".join(user_texts[-3:]) or "No explicit user goal captured yet"
        recent = "; ".join(assistant_texts[-2:]) or "No assistant decision captured yet"
        parts = []
        if existing_summary.strip():
            parts.append(f"Prior memory: {existing_summary.strip()[:500]}")
        parts.extend(
            [
                f"User goals: {goals[:350]}",
                f"Recent context: {recent[:350]}",
                "Preferences: keep answers grounded in the workspace documents and concise for voice.",
                "Open references: resolve pronouns from the latest turns only when document evidence supports the answer.",
            ]
        )
        return "\n".join(parts)[:1200]


def compact_title(value: str) -> str:
    cleaned = " ".join(value.replace("?", " ").replace(".", " ").split())
    if not cleaned:
        return "New chat"
    words = [
        word
        for word in cleaned.split()
        if word.lower() not in {"please", "can", "could", "you", "tell", "me", "what", "which", "does", "this", "the", "a", "an"}
    ]
    title_words = words[:5] or cleaned.split()[:5]
    title = " ".join(title_words).strip(" ,;:-")
    return title[:64] or "New chat"


def _clean(value: str) -> str:
    return " ".join(str(value or "").split())


def _needs_detailed_answer(question: str) -> bool:
    text = f" {str(question or '').lower()} "
    return any(
        cue in text
        for cue in [
            " explain ",
            " detail",
            " detailed",
            " why ",
            " how ",
            " compare",
            " process",
            " workflow",
            " steps",
            " describe",
            " elaborate",
            " full ",
            " overview",
        ]
    )
