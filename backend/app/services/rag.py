import math
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.gemini import generate_embeddings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MATCH_COUNT = 8
SIMILARITY_FLOOR = 0.5


async def retrieve_context(
    db: AsyncSession,
    query: str,
    meeting_id: Optional[UUID | str] = None,
    user_id: Optional[UUID | str] = None,
) -> List[Dict[str, Any]]:
    """
    Embed query and invoke match_transcript_chunks RPC via SQL.
    """
    embeddings = await generate_embeddings([query])
    if not embeddings:
        return []

    query_embedding = embeddings[0]

    sql = text("""
        SELECT * FROM public.match_transcript_chunks(
            query_embedding := :query_embedding::vector,
            match_count := :match_count,
            filter_meeting_id := :filter_meeting_id
        )
    """)

    result = await db.execute(
        sql,
        {
            "query_embedding": str(query_embedding),
            "match_count": MATCH_COUNT,
            "filter_meeting_id": str(meeting_id) if meeting_id else None,
        },
    )

    rows = result.mappings().all()

    filtered_chunks = [
        dict(row)
        for row in rows
        if float(row.get("similarity", 0.0)) >= SIMILARITY_FLOOR
    ]

    return filtered_chunks


def chunk_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Group transcript segments into retrieval-sized passages for RAG embedding.
    Uses character target length of 1200 (~300 tokens) and 1 segment of overlap.
    """
    if not segments:
        return []

    CHUNK_TARGET_CHARS = 1200
    OVERLAP_SEGMENTS = 1
    chunks = []
    i = 0

    while i < len(segments):
        slice_segs = []
        chars = 0
        j = i

        # Accumulate segments until we hit the character target
        while j < len(segments):
            slice_segs.append(segments[j])
            chars += len(segments[j].get("text", ""))
            j += 1
            if chars >= CHUNK_TARGET_CHARS:
                break

        content = "\n".join(
            [f"[{s.get('speaker', 'Speaker')}] {s.get('text', '')}" for s in slice_segs]
        )

        chunks.append({
            "chunk_index": len(chunks),
            "content": content,
            "start_ms": slice_segs[0].get("start_ms", 0),
            "end_ms": slice_segs[-1].get("end_ms", 0),
            "token_count": math.ceil(len(content) / 4),
        })

        # Advance: apply overlap only when we filled a full chunk.
        if j >= len(segments):
            i = j
        else:
            i = max(i + 1, j - OVERLAP_SEGMENTS)

    return chunks
