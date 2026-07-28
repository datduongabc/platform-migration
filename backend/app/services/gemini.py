import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.core.config import settings
from google import genai
from google.genai import types
from pydantic import BaseModel

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
EMBEDDING_MODEL = "text-embedding-004"


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
    segments: List[Dict[str, Any]], meeting_date: Optional[str] = None
) -> AnalysisResult:
    """
    Analyze transcript segments using Gemini Flash structured output.
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

    async def _execute(client: genai.Client):
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                response_mime_type="application/json",
                response_schema=AnalysisResult,
            ),
        )
        return AnalysisResult.model_validate_json(response.text)

    return await gemini_pool.call(_execute)


async def generate_embeddings(texts: List[str]) -> List[List[float]]:
    """
    Generate text embeddings using Gemini embedding model.
    Optimized to batch requests in a single call.
    """
    if not texts:
        return []

    async def _execute(client: genai.Client):
        res = await asyncio.to_thread(
            client.models.embed_content,
            model=EMBEDDING_MODEL,
            contents=texts,
        )
        if hasattr(res, "embeddings") and res.embeddings:
            return [emb.values for emb in res.embeddings]
        elif hasattr(res, "embedding") and res.embedding:
            return [res.embedding.values]
        return []

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
