// SERVER ONLY — retrieves transcript chunks semantically relevant to a user query.
//
// IMPORTANT: always pass a user-scoped client (createUserClient), never the
// service-role client. The match_transcript_chunks RPC is executed under the
// caller's JWT so RLS on transcript_chunks scopes results to the user's own
// meetings. Using the service role here would leak other users' data.

import type { SupabaseClient } from '@supabase/supabase-js'
import type { Database } from '@/types/database'
import { embedChunks } from '@/lib/gemini/embed'
import { EMBEDDING_DIMENSION } from '@/lib/gemini/client'

export const MATCH_COUNT = 8
// Chunks below this cosine similarity are dropped as off-topic noise.
export const SIMILARITY_FLOOR = 0.5

export interface RetrievedChunk {
  id: string
  meeting_id: string
  content: string
  start_ms: number
  end_ms: number
  similarity: number
}

/**
 * Embed the query, call match_transcript_chunks RPC, and apply a similarity floor.
 *
 * @param query - The user's natural-language question
 * @param userClient - A Supabase client created with the user's JWT (RLS applies)
 * @param meetingId - Scope to one meeting, or null for cross-meeting search
 * @param userId - Optional; forwarded to embedChunks for usage attribution
 */
export async function retrieveContext({
  query,
  userClient,
  meetingId = null,
  userId,
}: {
  query: string
  userClient: SupabaseClient<Database>
  meetingId?: string | null
  userId?: string | null
}): Promise<RetrievedChunk[]> {
  const embeddings = await embedChunks([query], {
    operation: 'embed-query',
    meetingId,
    userId,
  })
  const queryEmbedding = embeddings[0]

  if (queryEmbedding.length !== EMBEDDING_DIMENSION) {
    throw new Error(
      `Query embedding dimension ${queryEmbedding.length} !== stored dimension ${EMBEDDING_DIMENSION}`,
    )
  }

  const { data, error } = await userClient.rpc('match_transcript_chunks', {
    query_embedding: queryEmbedding,
    match_count: MATCH_COUNT,
    filter_meeting_id: meetingId ?? null,
  })

  if (error) throw new Error(`Retrieval RPC failed: ${error.message}`)

  return (data ?? []).filter((c) => c.similarity >= SIMILARITY_FLOOR)
}
