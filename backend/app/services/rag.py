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
        dict(row) for row in rows if float(row.get("similarity", 0.0)) >= SIMILARITY_FLOOR
    ]

    return filtered_chunks
