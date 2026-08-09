import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-3.5-flash-lite"


class TodoItem(BaseModel):
    content: str
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    source_segment_index: Optional[int] = None


class CalendarSuggestion(BaseModel):
    title: str
    proposed_at: Optional[str] = None
    raw_mention: str
    source_segment_index: Optional[int] = None


class AnalysisResult(BaseModel):
    summary: str
    notes_markdown: str
    todos: List[TodoItem] = []
    calendar_suggestions: List[CalendarSuggestion] = []


class KeyState:
    def __init__(self, key: str, index: int):
        self.key = key
        self.index = index
        self.cooldown_until = 0.0
        self.last_used_at = 0.0
        self.consecutive_failures = 0
        self.disabled = False


class GeminiKeyPool:
    def __init__(self, keys: List[str]):
        if not keys:
            keys = [settings.GEMINI_API_KEY]
        self.keys = [
            KeyState(k.strip(), i + 1) for i, k in enumerate(keys) if k.strip()
        ]

    def _next_key(self) -> Optional[KeyState]:
        now = time.time()
        healthy = [k for k in self.keys if not k.disabled and k.cooldown_until <= now]
        if not healthy:
            return None
        return min(healthy, key=lambda k: k.last_used_at)

    async def call(self, fn):
        max_attempts = max(len(self.keys) * 2, 8)
        last_err = None

        for attempt in range(max_attempts):
            key_state = self._next_key()

            if not key_state:
                await asyncio.sleep(1.0)
                continue

            key_state.last_used_at = time.time()
            client = genai.Client(api_key=key_state.key)

            try:
                result = await fn(client)
                key_state.consecutive_failures = 0
                return result
            except Exception as err:
                last_err = err
                err_msg = str(err)

                if (
                    "429" in err_msg
                    or "RESOURCE_EXHAUSTED" in err_msg
                    or "quota" in err_msg.lower()
                ):
                    key_state.cooldown_until = time.time() + 60.0
                    key_state.consecutive_failures += 1
                    logger.warning(
                        f"Gemini Key #{key_state.index} rate-limited. Cooling down 60s."
                    )
                elif "401" in err_msg or "API_KEY_INVALID" in err_msg:
                    key_state.disabled = True
                    logger.warning(
                        f"Gemini Key #{key_state.index} disabled due to 401 invalid key."
                    )
                else:
                    key_state.consecutive_failures += 1
                    logger.warning(
                        f"Gemini Key #{key_state.index} error: {err_msg[:120]}"
                    )

                await asyncio.sleep(min(0.5 * (2**attempt), 8.0))

        raise RuntimeError(
            f"All Gemini API keys exhausted after {max_attempts} attempts. Last error: {last_err}"
        )


# Initialize singleton key pool
gemini_pool = GeminiKeyPool([settings.GEMINI_API_KEY])


async def analyze_transcript(
    segments: List[Dict[str, Any]],
    meeting_date: Optional[str] = None,
    model: str = GEMINI_MODEL,
) -> AnalysisResult:
    """
    Analyze transcript segments using Gemini structured output.
    """
    if not segments:
        return AnalysisResult(
            summary="", notes_markdown="", todos=[], calendar_suggestions=[]
        )

    transcript_text = "\n".join(
        [
            f"[{i}] {s.get('speaker', 'Speaker')} ({(s.get('start_ms', 0) / 1000.0):.1f}s): {s.get('text', '')}"
            for i, s in enumerate(segments)
        ]
    )

    date_line = (
        f"MEETING_DATE: {meeting_date}" if meeting_date else "MEETING_DATE: (unknown)"
    )
    prompt = f"{date_line}\n\nTRANSCRIPT (prefixed with 0-based segment index [N]):\n{transcript_text}"

    system_instruction = (
        "You are an expert AI meeting analyst. Produce factual, concise meeting summaries, "
        "structured Markdown notes, todo action items with 0-based source_segment_index, "
        "and calendar suggestions."
    )

    async def _execute(client: genai.Client) -> AnalysisResult:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AnalysisResult,
            ),
        )
        # `_execute` previously had no return statement at all, so `res` was always
        # None and analysis silently fell through to the crude fallback below on
        # EVERY call, not just on real failures — no meeting ever got real Gemini
        # analysis. response.parsed holds the schema-validated Pydantic instance
        # when response_schema is set; fall back to manual parsing if the SDK
        # didn't populate it for some reason.
        if response.parsed is not None:
            return response.parsed
        return AnalysisResult.model_validate_json(response.text)

    res = await gemini_pool.call(_execute)
    if not res or not (res.summary or res.notes_markdown):
        # Structurally-valid-but-empty response — don't silently fabricate content
        # from raw transcript text and report success; let the caller's failure
        # handling (job retry/terminal-fail) take over, matching ricotdin's
        # assertAnalysisHasContent guard.
        raise RuntimeError(
            "Gemini analysis returned no summary or notes for this transcript."
        )
    return res


EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSION = 768  # must match transcript_chunks.embedding vector(768)


async def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate text embeddings using Gemini embedding model.
    """
    if not texts:
        return []

    embed_config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSION)

    async def _execute(client: genai.Client):
        res = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBEDDING_MODEL,
            contents=texts,
            config=embed_config,
        )
        if hasattr(res, "embeddings") and res.embeddings:
            embeddings = [emb.values for emb in res.embeddings]
        elif hasattr(res, "embedding") and res.embedding:
            embeddings = [res.embedding.values]
        else:
            raise RuntimeError(
                f"Gemini embed_content returned no embeddings for model {EMBEDDING_MODEL!r}."
            )

        if len(embeddings) != len(texts) or any(
            len(e) != EMBEDDING_DIMENSION for e in embeddings
        ):
            raise RuntimeError(
                f"Gemini embed_content returned malformed embeddings "
                f"(expected {len(texts)} vectors of dim {EMBEDDING_DIMENSION})."
            )
        return embeddings

    # No silent all-zero fallback: a zero vector still passes through the pipeline
    # as if embedding "succeeded", gets stored, and later scores as similarity ~0 —
    # indistinguishable from a genuine "no relevant content" RAG result, with the
    # quota charge for the query never refunded. Raising here lets the job worker's
    # normal retry/terminal-failure handling (and the chat route's refund-on-error
    # path) do the right thing instead.
    return await gemini_pool.call(_execute)


async def answer_question(query: str, context_chunks: List[Dict[str, Any]]) -> str:
    """
    Answer user question about a meeting based on retrieved transcript chunks.
    """
    context_text = "\n\n".join(
        [f"[{c.get('meeting_id', '')}] {c.get('content', '')}" for c in context_chunks]
    )

    prompt = f"CONTEXT CHUNKS:\n{context_text}\n\nUSER QUESTION: {query}"
    system_instruction = (
        "You are a helpful assistant. Answer the user's question using ONLY the provided context chunks. "
        "Be concise, accurate, and cite relevant parts if helpful."
    )

    async def _execute(client: genai.Client):
        res = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return res.text or ""

    return await gemini_pool.call(_execute)


class ChatCitation(BaseModel):
    chunk_id: str
    meeting_id: str
    start_ms: int
    end_ms: int


class ChatAnswerSchema(BaseModel):
    answer: str
    citations: List[ChatCitation] = []


async def answer_question_with_citations(
    query: str, context_chunks: List[Dict[str, Any]], history: List[Dict[str, str]] = []
) -> ChatAnswerSchema:
    """
    Grounded RAG answering with structured citations matching source chunks.
    """
    if not context_chunks:
        return ChatAnswerSchema(
            answer="I don't see that discussed in the meeting context.",
            citations=[],
        )

    # Build history text
    history_text = ""
    if history:
        history_text = "\n\nPrior conversation history:\n" + "\n".join(
            [
                f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
                for m in history
            ]
        )

    # Build excerpts text
    excerpts = "\n\n---\n\n".join(
        [
            f"chunk_id={c.get('id', '')} meeting_id={c.get('meeting_id', '')} start_ms={c.get('start_ms', 0)} end_ms={c.get('end_ms', 0)}\n{c.get('content', '')}"
            for c in context_chunks
        ]
    )

    prompt = (
        f"You are a meeting assistant. Answer the user's question using ONLY the transcript excerpts below.\n"
        f'If the answer is not in the excerpts, say clearly "I don\'t see that discussed in this meeting."\n'
        f"Do not invent or infer information beyond what is explicitly stated in the excerpts.\n"
        f"When citing, copy the chunk_id, meeting_id, start_ms, and end_ms values exactly from the excerpts — do not make up IDs.{history_text}\n\n"
        f"Transcript excerpts:\n{excerpts}\n\n"
        f"User question: {query}"
    )

    system_instruction = (
        "You are a helpful meeting chatbot. Answer the question based ONLY on the provided excerpts, "
        "and return the exact citations used."
    )

    async def _execute(client: genai.Client):
        res = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=ChatAnswerSchema,
            ),
        )
        return ChatAnswerSchema.model_validate_json(res.text)

    return await gemini_pool.call(_execute)
