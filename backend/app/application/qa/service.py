import re
from collections.abc import Iterator
from threading import Thread
from time import perf_counter

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.adapters.llm.local_llm_adapter import compact_title
from app.application.qa.context import build_context_pack, citations_from_results, context_profile
from app.application.workspaces.access import ensure_workspace_member
from app.domain.retrieval.entities import SearchResult
from app.infrastructure.db.models import (
    ChunkModel,
    CitationModel,
    ConversationModel,
    MessageModel,
    VoiceSessionModel,
    WorkspaceModel,
    utcnow,
)
from app.infrastructure.db.session import SessionLocal
from app.shared.ids import new_id
from app.shared.metrics import metrics
from app.shared.retry import retry_call


SUMMARY_MESSAGE_THRESHOLD = 12
SUMMARY_STALE_MESSAGE_THRESHOLD = 6
SUMMARY_CHAR_THRESHOLD = 3000
SUMMARY_MAX_MESSAGES = 18
SUMMARY_MAX_CHARACTERS = 1600


class QAService:
    def __init__(self, db: Session, embeddings, vector_search, llm) -> None:
        self.db = db
        self.embeddings = embeddings
        self.vector_search = vector_search
        self.llm = llm

    def search(self, user_id: str, workspace_id: str, query: str, document_ids: list[str] | None = None) -> list[dict]:
        results = self._retrieve_results(user_id, workspace_id, query, document_ids=document_ids, max_results=10)
        return [serialize_search_result(result) for result in results]

    def ask(
        self,
        user_id: str,
        workspace_id: str,
        question: str,
        conversation_id: str | None = None,
        document_ids: list[str] | None = None,
        mode: str = "text",
        voice_style_preference: str = "auto",
    ) -> dict:
        ensure_workspace_member(self.db, user_id, workspace_id)
        trace: dict[str, float] = {}
        profile = context_profile(mode)
        resolved_voice_style = self._workspace_voice_style_preference(workspace_id, voice_style_preference, mode)
        conversation_context = self._conversation_context(user_id, workspace_id, conversation_id, mode)
        retrieval_query = retrieval_query_with_memory(question, conversation_context)
        results = self._retrieve_results(
            user_id,
            workspace_id,
            retrieval_query,
            document_ids=document_ids,
            max_results=profile["max_results"],
            trace=trace,
        )
        context_pack = _timed(
            trace,
            "context_build",
            "qa.context_build_seconds",
            lambda: build_context_pack(
                question,
                results,
                mode=mode,
                conversation_context=conversation_context,
                voice_style_preference=resolved_voice_style,
            ),
        )
        answer = _timed(
            trace,
            "llm_response",
            "qa.llm_response_seconds",
            lambda: retry_call(lambda: self.llm.answer(question, context_pack), attempts=2),
        )
        if mode == "voice":
            answer = shape_voice_answer(answer, question)
        citations = citations_from_results(results)
        wiki_page_ids_by_chunk = {
            result.chunk_id: result.payload.get("wiki_page_id")
            for result in results
            if result.payload.get("wiki_page_id")
        }
        conversation = self._conversation(user_id, workspace_id, conversation_id, mode)
        user_message = MessageModel(id=new_id(), conversation_id=conversation.id, role="user", content=question)
        assistant_message = MessageModel(id=new_id(), conversation_id=conversation.id, role="assistant", content=answer)
        conversation.updated_at = utcnow()
        self.db.add_all([user_message, assistant_message])
        self.db.flush()
        for citation in citations:
            self.db.add(
                CitationModel(
                    id=new_id(),
                    message_id=assistant_message.id,
                    document_id=citation.document_id,
                    wiki_page_id=wiki_page_ids_by_chunk.get(citation.chunk_id),
                    chunk_id=citation.chunk_id,
                    page_number=citation.page_number,
                    quote=citation.quote,
                )
            )
        self.db.commit()
        self._schedule_conversation_title(conversation.id)
        self._schedule_conversation_summary(conversation.id)
        return {
            "answer": answer,
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "citations": [citation.__dict__ for citation in citations],
            "retrieved_context": [serialize_search_result(result) for result in results],
            "latency": trace,
            "context_stats": {
                "mode": mode,
                "result_count": len(results),
                "context_characters": len(context_pack),
                "conversation_memory_characters": len(conversation_context),
            },
        }

    def stream_ask_events(
        self,
        user_id: str,
        workspace_id: str,
        question: str,
        conversation_id: str | None = None,
        document_ids: list[str] | None = None,
        mode: str = "text",
        voice_style_preference: str = "auto",
    ) -> Iterator[dict]:
        ensure_workspace_member(self.db, user_id, workspace_id)
        trace: dict[str, float] = {}
        profile = context_profile(mode)
        resolved_voice_style = self._workspace_voice_style_preference(workspace_id, voice_style_preference, mode)
        conversation_context = self._conversation_context(user_id, workspace_id, conversation_id, mode)
        retrieval_query = retrieval_query_with_memory(question, conversation_context)
        results = self._retrieve_results(
            user_id,
            workspace_id,
            retrieval_query,
            document_ids=document_ids,
            max_results=profile["max_results"],
            trace=trace,
        )
        context_pack = _timed(
            trace,
            "context_build",
            "qa.context_build_seconds",
            lambda: build_context_pack(
                question,
                results,
                mode=mode,
                conversation_context=conversation_context,
                voice_style_preference=resolved_voice_style,
            ),
        )
        context_stats = {
            "mode": mode,
            "result_count": len(results),
            "context_characters": len(context_pack),
            "conversation_memory_characters": len(conversation_context),
        }
        yield {
            "type": "context_ready",
            "latency": trace,
            "context_stats": context_stats,
        }
        chunks = []
        llm_started = perf_counter()
        try:
            for delta in self.llm.stream_answer(question, context_pack):
                if not delta:
                    continue
                chunks.append(delta)
                yield {"type": "answer_delta", "delta": delta}
        finally:
            trace["llm_stream"] = perf_counter() - llm_started
            metrics.observe("qa.llm_stream_seconds", trace["llm_stream"])
        answer = "".join(chunks).strip()
        if not answer:
            answer = _timed(
                trace,
                "llm_response",
                "qa.llm_response_seconds",
                lambda: retry_call(lambda: self.llm.answer(question, context_pack), attempts=2),
            )
            yield {"type": "answer_delta", "delta": answer}
        if mode == "voice":
            answer = shape_voice_answer(answer, question)
        citations = citations_from_results(results)
        wiki_page_ids_by_chunk = {
            result.chunk_id: result.payload.get("wiki_page_id")
            for result in results
            if result.payload.get("wiki_page_id")
        }
        conversation = self._conversation(user_id, workspace_id, conversation_id, mode)
        user_message = MessageModel(id=new_id(), conversation_id=conversation.id, role="user", content=question)
        assistant_message = MessageModel(id=new_id(), conversation_id=conversation.id, role="assistant", content=answer)
        conversation.updated_at = utcnow()
        self.db.add_all([user_message, assistant_message])
        self.db.flush()
        for citation in citations:
            self.db.add(
                CitationModel(
                    id=new_id(),
                    message_id=assistant_message.id,
                    document_id=citation.document_id,
                    wiki_page_id=wiki_page_ids_by_chunk.get(citation.chunk_id),
                    chunk_id=citation.chunk_id,
                    page_number=citation.page_number,
                    quote=citation.quote,
                )
            )
        self.db.commit()
        self._schedule_conversation_title(conversation.id)
        self._schedule_conversation_summary(conversation.id)
        yield {
            "type": "final",
            "answer": answer,
            "conversation_id": conversation.id,
            "message_id": assistant_message.id,
            "citations": [citation.__dict__ for citation in citations],
            "latency": trace,
            "context_stats": context_stats,
        }

    def get_conversation(self, user_id: str, conversation_id: str) -> dict:
        conversation = self.db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        ensure_workspace_member(self.db, user_id, conversation.workspace_id)
        messages = (
            self.db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation.id)
            .order_by(MessageModel.created_at.asc())
            .all()
        )
        return {
            "id": conversation.id,
            "workspace_id": conversation.workspace_id,
            "user_id": conversation.user_id,
            "mode": conversation.mode,
            "memory_summary": conversation.memory_summary,
            "memory_updated_at": conversation.memory_updated_at.isoformat() if conversation.memory_updated_at else None,
            "memory_message_cursor": conversation.memory_message_cursor,
            "messages": [
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "created_at": message.created_at.isoformat(),
                }
                for message in messages
            ],
        }

    def list_conversations(self, user_id: str, workspace_id: str) -> list[dict]:
        ensure_workspace_member(self.db, user_id, workspace_id)
        rows = (
            self.db.query(ConversationModel)
            .filter(ConversationModel.user_id == user_id, ConversationModel.workspace_id == workspace_id)
            .order_by(ConversationModel.updated_at.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "workspace_id": row.workspace_id,
                "user_id": row.user_id,
                "mode": row.mode,
                "title": row.title or self._conversation_title(row.id),
                "message_count": self._conversation_message_count(row.id),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ]

    def delete_conversation(self, user_id: str, conversation_id: str) -> dict:
        conversation = self.db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
        if conversation is None or conversation.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        ensure_workspace_member(self.db, user_id, conversation.workspace_id)
        message_ids = [
            row.id
            for row in self.db.query(MessageModel.id)
            .filter(MessageModel.conversation_id == conversation.id)
            .all()
        ]
        if message_ids:
            self.db.query(CitationModel).filter(CitationModel.message_id.in_(message_ids)).delete(
                synchronize_session=False
            )
        self.db.query(VoiceSessionModel).filter(VoiceSessionModel.conversation_id == conversation.id).delete(
            synchronize_session=False
        )
        self.db.query(MessageModel).filter(MessageModel.conversation_id == conversation.id).delete(
            synchronize_session=False
        )
        self.db.delete(conversation)
        self.db.commit()
        return {"deleted": True, "conversation_id": conversation_id}

    def _retrieve_results(
        self,
        user_id: str,
        workspace_id: str,
        query: str,
        document_ids: list[str] | None = None,
        max_results: int = 10,
        trace: dict[str, float] | None = None,
    ) -> list[SearchResult]:
        ensure_workspace_member(self.db, user_id, workspace_id)
        normalized_query = normalize_question(query)
        vector = _timed(trace, "embedding", "qa.embedding_seconds", lambda: self.embeddings.embed(normalized_query or query))
        filters = {"user_id": user_id, "workspace_id": workspace_id}
        vector_results = _timed(
            trace,
            "vector_search",
            "qa.vector_search_seconds",
            lambda: self.vector_search.search(vector, filters=filters, limit=max_results),
        )
        vector_results = [result for result in vector_results if result.source_type.startswith("wiki")]
        keyword_results = _timed(
            trace,
            "keyword_search",
            "qa.keyword_search_seconds",
            lambda: self._keyword_search(user_id, workspace_id, normalized_query),
        )
        merged = self._merge_results(vector_results + keyword_results)
        backlinks = _timed(
            trace,
            "backlink_expansion",
            "qa.backlink_expansion_seconds",
            lambda: self._backlink_expansion(user_id, workspace_id, merged),
        )
        merged = self._merge_results(merged + backlinks)
        if document_ids:
            allowed = set(document_ids)
            merged = [result for result in merged if _matches_document_filter(result, allowed)]
        reranked = _timed(trace, "rerank", "qa.rerank_seconds", lambda: self._rerank(normalized_query, merged))
        return reranked[:max_results]

    def _keyword_search(self, user_id: str, workspace_id: str, query: str) -> list[SearchResult]:
        terms = [term for term in query.split() if len(term) > 2][:5]
        if not terms:
            return []
        filters = [ChunkModel.content.ilike(f"%{term}%") for term in terms]
        rows = (
            self.db.query(ChunkModel)
            .filter(
                ChunkModel.user_id == user_id,
                ChunkModel.workspace_id == workspace_id,
                ChunkModel.source_type.in_(["wiki", "wiki_index", "wiki_backlinks"]),
                or_(*filters),
            )
            .limit(8)
            .all()
        )
        return [
            SearchResult(
                chunk_id=row.id,
                score=0.55,
                source_type=row.source_type,
                content=row.content,
                payload={
                    **(row.metadata_json or {}),
                    "user_id": row.user_id,
                    "workspace_id": row.workspace_id,
                    "document_id": row.document_id,
                    "wiki_page_id": row.wiki_page_id,
                    "source_type": row.source_type,
                    "title": row.title,
                    "heading": row.heading,
                    "path": row.path,
                    "page_number": row.page_number,
                    "content_preview": row.content[:300],
                },
            )
            for row in rows
        ]

    def _backlink_expansion(self, user_id: str, workspace_id: str, results: list[SearchResult]) -> list[SearchResult]:
        document_ids = {
            document_id
            for result in results
            for document_id in _linked_document_ids(result)
            if document_id
        }
        if not document_ids:
            return []
        rows = (
            self.db.query(ChunkModel)
            .filter(
                ChunkModel.user_id == user_id,
                ChunkModel.workspace_id == workspace_id,
                ChunkModel.source_type.in_(["wiki", "wiki_index", "wiki_backlinks"]),
            )
            .limit(200)
            .all()
        )
        expanded = []
        for row in rows:
            linked = set((row.metadata_json or {}).get("linked_raw_documents") or [])
            if row.document_id in document_ids or linked.intersection(document_ids):
                expanded.append(
                    SearchResult(
                        chunk_id=row.id,
                        score=0.5,
                        source_type=row.source_type,
                        content=row.content,
                        payload={
                            **(row.metadata_json or {}),
                            "user_id": row.user_id,
                            "workspace_id": row.workspace_id,
                            "document_id": row.document_id,
                            "wiki_page_id": row.wiki_page_id,
                            "source_type": row.source_type,
                            "title": row.title,
                            "heading": row.heading,
                            "path": row.path,
                            "page_number": row.page_number,
                            "content_preview": row.content[:300],
                        },
                    )
                )
        return expanded

    def _merge_results(self, results: list[SearchResult]) -> list[SearchResult]:
        merged = {}
        for result in results:
            existing = merged.get(result.chunk_id)
            if existing is None or result.score > existing.score:
                merged[result.chunk_id] = result
        return sorted(merged.values(), key=lambda result: result.score, reverse=True)

    def _rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        query_terms = set(query.split())

        def rank(result: SearchResult) -> float:
            text = normalize_question(" ".join([result.content, str(result.payload.get("title") or ""), str(result.payload.get("heading") or "")]))
            result_terms = set(text.split())
            overlap = len(query_terms.intersection(result_terms))
            source_boost = 0.2 if result.source_type == "wiki" else 0.08 if result.source_type.startswith("wiki_") else 0
            return result.score + (overlap * 0.04) + source_boost

        return sorted(results, key=rank, reverse=True)

    def _conversation(self, user_id: str, workspace_id: str, conversation_id: str | None, mode: str) -> ConversationModel:
        if conversation_id:
            conversation = self.db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
            if conversation is None or conversation.user_id != user_id or conversation.workspace_id != workspace_id:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
            ensure_workspace_member(self.db, user_id, conversation.workspace_id)
            return conversation
        conversation = ConversationModel(id=new_id(), workspace_id=workspace_id, user_id=user_id, mode=mode)
        self.db.add(conversation)
        self.db.flush()
        return conversation

    def _conversation_context(
        self,
        user_id: str,
        workspace_id: str,
        conversation_id: str | None,
        mode: str,
    ) -> str:
        if not conversation_id:
            return ""
        conversation = self.db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
        if conversation is None or conversation.user_id != user_id or conversation.workspace_id != workspace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        ensure_workspace_member(self.db, user_id, conversation.workspace_id)
        profile = context_profile(mode)
        summary = conversation.memory_summary or ""
        summary_budget = min(len(summary), max(0, profile["history_char_limit"] // 2))
        remaining_budget = max(0, profile["history_char_limit"] - summary_budget)
        messages = (
            self.db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation.id, MessageModel.role.in_(["user", "assistant"]))
            .order_by(MessageModel.created_at.desc())
            .limit(profile["history_message_limit"])
            .all()
        )
        recent_context = format_conversation_context(list(reversed(messages)), remaining_budget)
        return combine_conversation_memory(summary, recent_context, profile["history_char_limit"])

    def _conversation_title(self, conversation_id: str) -> str:
        message = (
            self.db.query(MessageModel)
            .filter(MessageModel.conversation_id == conversation_id, MessageModel.role == "user")
            .order_by(MessageModel.created_at.asc())
            .first()
        )
        if message is None:
            return "New chat"
        return compact_title(message.content)

    def _schedule_conversation_title(self, conversation_id: str) -> None:
        if not hasattr(self.llm, "title"):
            return
        if getattr(self.llm, "api_key", ""):
            Thread(target=self._generate_conversation_title, args=(conversation_id,), daemon=True).start()
            return
        self._generate_conversation_title(conversation_id)

    def _generate_conversation_title(self, conversation_id: str) -> None:
        try:
            with SessionLocal() as db:
                conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
                if conversation is None or conversation.title:
                    return
                messages = (
                    db.query(MessageModel)
                    .filter(MessageModel.conversation_id == conversation_id, MessageModel.role.in_(["user", "assistant"]))
                    .order_by(MessageModel.created_at.asc())
                    .limit(6)
                    .all()
                )
                if not messages:
                    return
                title = self.llm.title([{"role": message.role, "content": message.content} for message in messages])
                if not title:
                    return
                conversation.title = title[:120]
                db.commit()
        except SQLAlchemyError:
            return

    def _schedule_conversation_summary(self, conversation_id: str) -> None:
        if not hasattr(self.llm, "summarize_conversation"):
            return
        Thread(target=self._summarize_conversation, args=(conversation_id,), daemon=True).start()

    def _summarize_conversation(self, conversation_id: str) -> None:
        try:
            with SessionLocal() as db:
                conversation = db.query(ConversationModel).filter(ConversationModel.id == conversation_id).first()
                if conversation is None:
                    return
                messages = (
                    db.query(MessageModel)
                    .filter(MessageModel.conversation_id == conversation_id, MessageModel.role.in_(["user", "assistant"]))
                    .order_by(MessageModel.created_at.asc())
                    .all()
                )
                if not conversation_needs_summary(conversation, messages):
                    return
                new_messages = messages_since_cursor(messages, conversation.memory_message_cursor)
                if not new_messages:
                    return
                summary = self.llm.summarize_conversation(
                    conversation.memory_summary or "",
                    [{"role": message.role, "content": message.content} for message in new_messages[-SUMMARY_MAX_MESSAGES:]],
                )
                if not summary:
                    return
                conversation.memory_summary = " ".join(str(summary).split())[:SUMMARY_MAX_CHARACTERS]
                conversation.memory_updated_at = utcnow()
                conversation.memory_message_cursor = messages[-1].id
                db.commit()
        except SQLAlchemyError:
            return

    def _conversation_message_count(self, conversation_id: str) -> int:
        return self.db.query(MessageModel).filter(MessageModel.conversation_id == conversation_id).count()

    def _workspace_voice_style_preference(self, workspace_id: str, requested_preference: str, mode: str) -> str:
        if mode != "voice":
            return requested_preference
        normalized_request = (requested_preference or "auto").strip().lower().replace("-", "_")
        if normalized_request != "auto":
            return normalized_request
        row = self.db.query(WorkspaceModel.voice_style_preference).filter(WorkspaceModel.id == workspace_id).first()
        return row[0] if row and row[0] else "auto"


def serialize_search_result(result: SearchResult) -> dict:
    return {
        "chunk_id": result.chunk_id,
        "score": result.score,
        "source_type": result.source_type,
        "content": result.content,
        "payload": result.payload,
    }


def normalize_question(question: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", question.lower())
    return " ".join(normalized.split())


def retrieval_query_with_memory(question: str, conversation_context: str) -> str:
    if not conversation_context.strip():
        return question
    return f"{conversation_context.strip()}\nCurrent question: {question}"


def combine_conversation_memory(summary: str, recent_context: str, char_limit: int) -> str:
    parts = []
    if summary.strip():
        parts.append(f"Memory summary:\n{summary.strip()}")
    if recent_context.strip():
        parts.append(f"Recent turns:\n{recent_context.strip()}")
    combined = "\n\n".join(parts)
    if len(combined) <= char_limit:
        return combined
    return f"{combined[: max(0, char_limit - 3)].rstrip()}..."


def format_conversation_context(messages, char_limit: int) -> str:
    if char_limit <= 0:
        return ""
    lines = []
    used = 0
    for message in messages:
        if message.role not in {"user", "assistant"}:
            continue
        content = " ".join(str(message.content or "").split())
        if not content:
            continue
        role = "User" if message.role == "user" else "Assistant"
        line = f"{role}: {content}"
        remaining = char_limit - used
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = f"{line[: max(0, remaining - 3)].rstrip()}..."
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def conversation_needs_summary(conversation, messages) -> bool:
    if len(messages) < SUMMARY_MESSAGE_THRESHOLD:
        return False
    if not conversation.memory_message_cursor:
        return True
    new_messages = messages_since_cursor(messages, conversation.memory_message_cursor)
    if len(new_messages) >= SUMMARY_STALE_MESSAGE_THRESHOLD:
        return True
    return sum(len(str(message.content or "")) for message in new_messages) >= SUMMARY_CHAR_THRESHOLD


def messages_since_cursor(messages, cursor: str | None):
    if not cursor:
        return list(messages)
    for index, message in enumerate(messages):
        if message.id == cursor:
            return list(messages[index + 1 :])
    return list(messages)


def shape_voice_answer(answer: str, question: str) -> str:
    normalized = " ".join(answer.split())
    if not normalized:
        return normalized
    question_lower = question.lower()
    detailed_request = bool(
        re.search(
            r"\b(learn|understand|explain|teach|why|how|walk me through|detail|detailed|compare|comparison|steps|process|describe|elaborate)\b",
            question_lower,
        )
    )
    wants_one_sentence = "one sentence" in question_lower or "short" in question_lower or "quick" in question_lower
    sentence_limit = 1 if wants_one_sentence else 4 if detailed_request else 2
    word_limit = 32 if wants_one_sentence else 120 if detailed_request else 70
    sentences = split_sentences(normalized)
    shaped = " ".join(sentences[:sentence_limit]) if sentences else normalized
    return limit_words(shaped, word_limit)


def split_sentences(text: str) -> list[str]:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
    return sentences or [text.strip()]


def limit_words(text: str, word_limit: int) -> str:
    words = text.split()
    if len(words) <= word_limit:
        return text
    trimmed = " ".join(words[:word_limit]).rstrip(" ,;:")
    return f"{trimmed}."


def _linked_document_ids(result: SearchResult) -> set[str]:
    linked = result.payload.get("linked_raw_documents") or []
    ids = set(linked if isinstance(linked, list) else [])
    document_id = result.payload.get("document_id")
    if document_id:
        ids.add(document_id)
    return ids


def _matches_document_filter(result: SearchResult, allowed_document_ids: set[str]) -> bool:
    return bool(_linked_document_ids(result).intersection(allowed_document_ids))


def _timed(trace: dict[str, float] | None, key: str, metric_name: str, func):
    start = perf_counter()
    try:
        return func()
    finally:
        seconds = perf_counter() - start
        metrics.observe(metric_name, seconds)
        if trace is not None:
            trace[key] = seconds
