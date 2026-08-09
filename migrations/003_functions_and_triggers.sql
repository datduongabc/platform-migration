-- ============================================================================
-- Migration 003: Core Stored Procedures and Triggers
-- Target: Automatic user setup, quota movements, and RAG vector search
-- ============================================================================

-- 1. Automatic User Setup Function & Trigger
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  base_username TEXT;
  final_username TEXT;
  counter INT := 0;
BEGIN
  -- Generate unique username from email
  base_username := LOWER(SPLIT_PART(COALESCE(NEW.email, 'user'), '@', 1));
  base_username := REGEXP_REPLACE(base_username, '[^a-z0-9_-]', '', 'g');
  IF LENGTH(base_username) < 3 THEN
    base_username := 'user_' || SUBSTRING(NEW.id::text FROM 1 FOR 6);
  END IF;
  
  final_username := base_username;
  WHILE EXISTS (SELECT 1 FROM public.profiles WHERE username = final_username) LOOP
    counter := counter + 1;
    final_username := base_username || counter::text;
  END LOOP;

  -- Insert profile
  INSERT INTO public.profiles (id, username, display_name, role)
  VALUES (
    NEW.id,
    final_username,
    COALESCE(NEW.raw_user_meta_data->>'display_name', final_username),
    'user'
  )
  ON CONFLICT (id) DO NOTHING;

  -- Initialize quota wallet (1 hour audio = 3600s, 50 agent queries — ricotdin parity:
  -- SIGNUP_AUDIO_SECONDS / SIGNUP_AGENT_QUERIES).
  INSERT INTO public.quota_wallets (user_id, audio_seconds_remaining, agent_queries_remaining)
  VALUES (NEW.id, 3600, 50)
  ON CONFLICT (user_id) DO NOTHING;

  -- Mirror the grant into the ledger so quota_wallets and quota_movements agree from
  -- the start. Without this row, reconcile_wallets() sees ledger_sum=0 vs wallet=3600/50,
  -- treats the whole signup grant as drift, and "corrects" it back to zero.
  INSERT INTO public.quota_movements (user_id, delta_audio_seconds, delta_agent_queries, reason, dedup_key)
  VALUES (NEW.id, 3600, 50, 'topup', 'signup:' || NEW.id::text)
  ON CONFLICT (dedup_key) DO NOTHING;

  RETURN NEW;
END;
$$;

-- Attach trigger to auth.users if auth schema exists
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = 'auth') THEN
    DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
    CREATE TRIGGER on_auth_user_created
      AFTER INSERT ON auth.users
      FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();
  END IF;
END $$;

-- 2. Quota Movement Helper Function
-- Drop the old FLOAT-typed overload first: changing parameter/return types is
-- not something CREATE OR REPLACE can do in place — Postgres identifies
-- functions by their full type signature, so without this DROP, re-running this
-- migration against a database that still has the old FLOAT version creates a
-- SECOND overload instead of replacing it (ambiguous-call errors and, worse,
-- callers silently resolving to whichever one Postgres picks).
DROP FUNCTION IF EXISTS public.quota_apply_movement(
  UUID, FLOAT, INT, TEXT, TEXT, BOOLEAN, UUID, UUID, JSONB
);

CREATE OR REPLACE FUNCTION public.quota_apply_movement(
  p_user_id              UUID,
  p_delta_audio_seconds  BIGINT DEFAULT 0,
  p_delta_agent_queries  INT DEFAULT 0,
  p_reason               TEXT DEFAULT 'usage',
  p_dedup_key            TEXT DEFAULT NULL,
  p_allow_overdraw       BOOLEAN DEFAULT FALSE,
  p_meeting_id           UUID DEFAULT NULL,
  p_created_by           UUID DEFAULT NULL,
  p_metadata             JSONB DEFAULT '{}'::jsonb
)
RETURNS TABLE (
  status                    TEXT,
  audio_seconds_remaining   BIGINT,
  agent_queries_remaining   INT
)
LANGUAGE plpgsql
SECURITY DEFINER SET search_path = public
AS $$
DECLARE
  v_curr_audio   BIGINT;
  v_curr_queries INT;
  v_new_audio    BIGINT;
  v_new_queries  INT;
BEGIN
  -- Idempotency check: if dedup_key provided and already logged, return current wallet
  IF p_dedup_key IS NOT NULL AND EXISTS (SELECT 1 FROM public.quota_movements WHERE dedup_key = p_dedup_key) THEN
    SELECT qw.audio_seconds_remaining, qw.agent_queries_remaining
      INTO v_curr_audio, v_curr_queries
      FROM public.quota_wallets qw
     WHERE qw.user_id = p_user_id;

    RETURN QUERY SELECT 'already_processed'::TEXT, COALESCE(v_curr_audio, 0), COALESCE(v_curr_queries, 0);
    RETURN;
  END IF;

  -- Ensure wallet exists
  INSERT INTO public.quota_wallets (user_id)
  VALUES (p_user_id)
  ON CONFLICT (user_id) DO NOTHING;

  -- Lock wallet row for update
  SELECT qw.audio_seconds_remaining, qw.agent_queries_remaining
    INTO v_curr_audio, v_curr_queries
    FROM public.quota_wallets qw
   WHERE qw.user_id = p_user_id
     FOR UPDATE;

  v_new_audio := v_curr_audio + p_delta_audio_seconds;
  v_new_queries := v_curr_queries + p_delta_agent_queries;

  -- Check overdraw condition if not allowed. When this branch doesn't return early,
  -- v_new_audio/v_new_queries are already guaranteed >= 0.
  IF NOT p_allow_overdraw THEN
    IF v_new_audio < 0 OR v_new_queries < 0 THEN
      RETURN QUERY SELECT 'insufficient'::TEXT, v_curr_audio, v_curr_queries;
      RETURN;
    END IF;
  END IF;

  -- Update wallet. Do NOT clamp with GREATEST(0, ...): when p_allow_overdraw is true
  -- (settle/refund/adjustment), the wallet is allowed to go genuinely negative on
  -- purpose, and the ledger row below always logs the *unclamped* delta — clamping
  -- only the wallet here silently desynced wallet vs. ledger, and reconcile_wallets()
  -- would then "correct" that manufactured drift every cycle, compounding forever.
  UPDATE public.quota_wallets
     SET audio_seconds_remaining = v_new_audio,
         agent_queries_remaining = v_new_queries,
         updated_at = NOW()
   WHERE user_id = p_user_id;

  -- Log movement
  INSERT INTO public.quota_movements (
    user_id, meeting_id, delta_audio_seconds, delta_agent_queries, reason, dedup_key
  ) VALUES (
    p_user_id, p_meeting_id, p_delta_audio_seconds, p_delta_agent_queries, p_reason, p_dedup_key
  );

  RETURN QUERY SELECT 'ok'::TEXT, v_new_audio, v_new_queries;
END;
$$;

-- 3. RAG Vector Search RPC Function (pgvector match_transcript_chunks)
-- filter_user_id scopes results to meetings the caller owns or has folder-share
-- access to. Previously this function had no ownership filter at all — the global
-- (filter_meeting_id IS NULL) chat mode did an unrestricted vector search across
-- every user's transcripts, and app/services/rag.py silently discarded the user_id
-- it was already given. Callers MUST always pass filter_user_id; the NULL default
-- exists only so an explicit, deliberate cross-tenant admin/maintenance query can
-- still opt out — no ordinary application code path should ever omit it.
CREATE OR REPLACE FUNCTION public.match_transcript_chunks(
  query_embedding   vector(768),
  match_count       INT DEFAULT 8,
  filter_meeting_id UUID DEFAULT NULL,
  filter_user_id    UUID DEFAULT NULL,
  filter_folder_id  UUID DEFAULT NULL
)
RETURNS TABLE (
  id          UUID,
  meeting_id  UUID,
  content     TEXT,
  start_ms    INT,
  end_ms      INT,
  similarity  FLOAT
)
LANGUAGE sql
STABLE
AS $$
  SELECT
    c.id,
    c.meeting_id,
    c.content,
    c.start_ms,
    c.end_ms,
    1 - (c.embedding <=> query_embedding) AS similarity
  FROM public.transcript_chunks c
  JOIN public.meetings m ON m.id = c.meeting_id
  WHERE (filter_meeting_id IS NULL OR c.meeting_id = filter_meeting_id)
    AND (filter_folder_id IS NULL OR m.folder_id = filter_folder_id)
    AND (
      filter_user_id IS NULL
      OR m.user_id = filter_user_id
      OR EXISTS (
        SELECT 1 FROM public.folder_shares fs
        WHERE fs.folder_id = m.folder_id AND fs.user_id = filter_user_id
      )
    )
  ORDER BY c.embedding <=> query_embedding
  LIMIT match_count;
$$;

-- 4. Atomic Worker Job Queue Claim Function
CREATE OR REPLACE FUNCTION public.claim_next_job(p_worker_id TEXT)
RETURNS SETOF public.jobs
LANGUAGE sql
SECURITY DEFINER SET search_path = public
AS $$
  UPDATE public.jobs
  SET    status     = 'running',
         locked_at  = NOW(),
         locked_by  = p_worker_id,
         updated_at = NOW()
  WHERE  id = (
    SELECT id FROM public.jobs
    WHERE  status    = 'queued'
      AND  run_after <= NOW()
    ORDER  BY run_after ASC
    LIMIT  1
    FOR UPDATE SKIP LOCKED
  )
  RETURNING *;
$$;
