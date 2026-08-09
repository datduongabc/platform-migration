-- ============================================================================
-- Migration 002: Core Schema Tables and Optimized Indexes
-- Consolidated baseline schema without redundant column additions or dead indexes
-- ============================================================================

-- 1. Profiles Table (User profile, avatar_key, role, theme preference)
CREATE TABLE IF NOT EXISTS public.profiles (
  id               UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  username         TEXT UNIQUE NOT NULL,
  display_name     TEXT,
  avatar_key       TEXT,
  theme_preference TEXT DEFAULT 'luxury',
  role             TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  default_provider TEXT,
  default_model    TEXT,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT profiles_model_pref_both_or_neither
    CHECK ((default_provider IS NULL) = (default_model IS NULL))
);

CREATE TRIGGER trg_profiles_updated_at
  BEFORE UPDATE ON public.profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_profiles_username ON public.profiles (username);
CREATE INDEX IF NOT EXISTS idx_profiles_role ON public.profiles (role);

-- 2. Folders Table (Folder hierarchy & positions)
CREATE TABLE IF NOT EXISTS public.folders (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  position    INTEGER DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_folders_updated_at
  BEFORE UPDATE ON public.folders
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_folders_user_id ON public.folders (user_id);
CREATE INDEX IF NOT EXISTS idx_folders_position ON public.folders (user_id, position);

-- Case-insensitive per-owner uniqueness (ricotdin parity: migrations/011_folders.sql).
-- Without this, two concurrent creates with the same name both succeed.
CREATE UNIQUE INDEX IF NOT EXISTS idx_folders_user_name_ci ON public.folders (user_id, lower(name));

-- 3. Meetings Table (Recorded meetings, audio path, processing status & metadata)
CREATE TABLE IF NOT EXISTS public.meetings (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  folder_id        UUID REFERENCES public.folders (id) ON DELETE SET NULL,
  title            TEXT NOT NULL DEFAULT 'Untitled meeting',
  status           meeting_status NOT NULL DEFAULT 'pending',
  pinned           BOOLEAN NOT NULL DEFAULT FALSE,
  pinned_at        TIMESTAMPTZ,
  source           TEXT DEFAULT 'upload',
  source_video     BOOLEAN DEFAULT FALSE,
  storage_provider TEXT DEFAULT 'r2' CHECK (storage_provider IN ('r2', 's3', 'supabase')),
  model_lock       TEXT,
  audio_path       TEXT,
  duration_seconds INTEGER,
  language         TEXT,
  summary          TEXT,
  notes            TEXT,
  error_message    TEXT,
  started_at       TIMESTAMPTZ,
  created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_meetings_updated_at
  BEFORE UPDATE ON public.meetings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_meetings_user_id ON public.meetings (user_id);
CREATE INDEX IF NOT EXISTS idx_meetings_folder_id ON public.meetings (folder_id);
CREATE INDEX IF NOT EXISTS idx_meetings_status ON public.meetings (status);
CREATE INDEX IF NOT EXISTS idx_meetings_pinned ON public.meetings (user_id, pinned) WHERE pinned = TRUE;
CREATE INDEX IF NOT EXISTS idx_meetings_created_at ON public.meetings (created_at DESC);

-- 4. Transcript Segments Table (Time-stamped utterances)
CREATE TABLE IF NOT EXISTS public.transcript_segments (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id    UUID NOT NULL REFERENCES public.meetings (id) ON DELETE CASCADE,
  segment_index INTEGER NOT NULL,
  speaker       TEXT,
  start_ms      INTEGER NOT NULL,
  end_ms        INTEGER NOT NULL,
  text          TEXT NOT NULL,
  confidence    FLOAT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (meeting_id, segment_index)
);

CREATE INDEX IF NOT EXISTS idx_segments_meeting ON public.transcript_segments (meeting_id, segment_index);

-- 5. Transcript Chunks Table (Vector embedding store for RAG with HNSW index)
CREATE TABLE IF NOT EXISTS public.transcript_chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id  UUID NOT NULL REFERENCES public.meetings (id) ON DELETE CASCADE,
  chunk_index INTEGER NOT NULL,
  content     TEXT NOT NULL,
  embedding   vector(768) NOT NULL,
  start_ms    INTEGER,
  end_ms      INTEGER,
  token_count INTEGER,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (meeting_id, chunk_index)
);

-- Tuned HNSW Index for fast cosine similarity search (m=16, ef_construction=64)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON public.transcript_chunks
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_chunks_meeting ON public.transcript_chunks (meeting_id);

-- 6. Todos Table (Action items extracted from meetings)
CREATE TABLE IF NOT EXISTS public.todos (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id        UUID NOT NULL REFERENCES public.meetings (id) ON DELETE CASCADE,
  content           TEXT NOT NULL,
  assignee          TEXT,
  due_date          DATE,
  status            todo_status NOT NULL DEFAULT 'open',
  source_segment_id UUID REFERENCES public.transcript_segments (id) ON DELETE SET NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_todos_updated_at
  BEFORE UPDATE ON public.todos
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_todos_meeting ON public.todos (meeting_id);
CREATE INDEX IF NOT EXISTS idx_todos_status ON public.todos (status);

-- 7. Calendar Suggestions Table
CREATE TABLE IF NOT EXISTS public.calendar_suggestions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id        UUID NOT NULL REFERENCES public.meetings (id) ON DELETE CASCADE,
  title             TEXT NOT NULL,
  proposed_at       TIMESTAMPTZ,
  raw_mention       TEXT,
  source_segment_id UUID REFERENCES public.transcript_segments (id) ON DELETE SET NULL,
  dismissed         BOOLEAN NOT NULL DEFAULT FALSE,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calsug_meeting ON public.calendar_suggestions (meeting_id);

-- 8. Folder Shares Table (Folder sharing with permissions)
CREATE TABLE IF NOT EXISTS public.folder_shares (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  folder_id   UUID NOT NULL REFERENCES public.folders (id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  role        folder_role NOT NULL DEFAULT 'viewer',
  invited_by  UUID REFERENCES auth.users (id) ON DELETE SET NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (folder_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_folder_shares_user ON public.folder_shares (user_id);
CREATE INDEX IF NOT EXISTS idx_folder_shares_folder ON public.folder_shares (folder_id);

-- 9. Chat Sessions & Chat Messages Tables
CREATE TABLE IF NOT EXISTS public.chat_sessions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  meeting_id  UUID REFERENCES public.meetings (id) ON DELETE CASCADE,
  folder_id   UUID REFERENCES public.folders (id) ON DELETE CASCADE,
  title       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_chat_sessions_updated_at
  BEFORE UPDATE ON public.chat_sessions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_chat_sessions_user ON public.chat_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_meeting ON public.chat_sessions (meeting_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_folder ON public.chat_sessions (folder_id);

CREATE TABLE IF NOT EXISTS public.chat_messages (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  UUID NOT NULL REFERENCES public.chat_sessions (id) ON DELETE CASCADE,
  role        chat_role NOT NULL,
  content     TEXT NOT NULL,
  citations   JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON public.chat_messages (session_id, created_at ASC);

-- 10. Quota Wallets & Movements Tables
CREATE TABLE IF NOT EXISTS public.quota_wallets (
  user_id                 UUID PRIMARY KEY REFERENCES auth.users (id) ON DELETE CASCADE,
  -- BIGINT, not FLOAT (ricotdin parity) — audio seconds are always whole numbers
  -- (see jobs.py's math.ceil() on real Speechmatics duration before settling);
  -- float arithmetic here produced drift like 0.8600000000000136 in the ledger.
  audio_seconds_remaining BIGINT NOT NULL DEFAULT 3600,
  agent_queries_remaining INTEGER NOT NULL DEFAULT 100,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_quota_wallets_updated_at
  BEFORE UPDATE ON public.quota_wallets
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS public.quota_movements (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
  meeting_id           UUID REFERENCES public.meetings (id) ON DELETE SET NULL,
  delta_audio_seconds  BIGINT NOT NULL DEFAULT 0,
  delta_agent_queries  INTEGER NOT NULL DEFAULT 0,
  reason               TEXT NOT NULL CHECK (reason IN ('topup', 'admin_grant', 'generate', 'agent_query', 'refund', 'adjustment')),
  dedup_key            TEXT UNIQUE,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quota_movements_user ON public.quota_movements (user_id, created_at DESC);

-- 11. Activity Log Table
-- Columns match what app/api/endpoints/{projects,admin}.py and app/services/jobs.py
-- actually read/write (event_type/meeting_id/metadata/ip/user_agent) — the previous
-- action/details/level shape didn't match any query and every insert failed silently.
CREATE TABLE IF NOT EXISTS public.activity_log (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES auth.users (id) ON DELETE SET NULL,
  event_type  TEXT NOT NULL CHECK (event_type IN (
                'login', 'logout',
                'record_start', 'record_stop',
                'meeting_created', 'processing_done', 'processing_failed',
                'chat_message', 'meeting_deleted',
                'meeting_shared', 'meeting_unshared'
              )),
  meeting_id  UUID REFERENCES public.meetings (id) ON DELETE SET NULL,
  metadata    JSONB DEFAULT '{}'::jsonb,
  ip          TEXT,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_activity_log_user ON public.activity_log (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_event_type ON public.activity_log (event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_activity_log_meeting ON public.activity_log (meeting_id) WHERE meeting_id IS NOT NULL;

-- 12. App & Admin Config Tables
CREATE TABLE IF NOT EXISTS public.app_config (
  key         TEXT PRIMARY KEY,
  value       JSONB NOT NULL,
  description TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Column names match app/api/endpoints/admin.py's add_key/list_keys/trigger_healthcheck
-- (value_ciphertext/value_iv/value_auth_tag) — the previous secret_* names didn't match
-- any query, so key creation and health-check both failed with "column does not exist".
CREATE TABLE IF NOT EXISTS public.admin_config (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  config_key         TEXT NOT NULL,
  label              TEXT NOT NULL,
  value_ciphertext   TEXT NOT NULL,
  value_iv           TEXT NOT NULL,
  value_auth_tag     TEXT NOT NULL,
  last4              TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  disabled_reason    TEXT,
  last_used_at       TIMESTAMPTZ,
  health_status      TEXT DEFAULT 'unknown' CHECK (health_status IN ('healthy', 'unhealthy', 'unknown')),
  health_checked_at  TIMESTAMPTZ,
  health_detail      TEXT,
  created_by         UUID REFERENCES auth.users (id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.storage_config (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  provider           TEXT NOT NULL DEFAULT 'r2' CHECK (provider IN ('r2')),
  label              TEXT NOT NULL,
  account_id         TEXT NOT NULL,
  access_key_id      TEXT NOT NULL,
  secret_ciphertext  TEXT NOT NULL,
  secret_iv          TEXT NOT NULL,
  secret_auth_tag    TEXT NOT NULL,
  secret_last4       TEXT NOT NULL,
  bucket             TEXT NOT NULL,
  status             TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
  disabled_reason    TEXT,
  last_used_at       TIMESTAMPTZ,
  created_by         UUID REFERENCES auth.users (id) ON DELETE SET NULL,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.features (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key         TEXT UNIQUE NOT NULL,
  enabled     BOOLEAN NOT NULL DEFAULT TRUE,
  description TEXT,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.ai_registry (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL UNIQUE,
  provider    TEXT NOT NULL,
  is_active   BOOLEAN NOT NULL DEFAULT TRUE,
  config      JSONB DEFAULT '{}'::jsonb,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 13. Jobs Queue Table (Background processing pipeline)
CREATE TABLE IF NOT EXISTS public.jobs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  meeting_id   UUID NOT NULL REFERENCES public.meetings (id) ON DELETE CASCADE,
  step         TEXT NOT NULL DEFAULT 'start' CHECK (step IN ('start', 'transcribe_poll', 'analyse', 'embed')),
  status       TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 5,
  last_error   TEXT,
  run_after    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  locked_at    TIMESTAMPTZ,
  locked_by    TEXT,
  payload      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_jobs_updated_at
  BEFORE UPDATE ON public.jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS jobs_claim_idx ON public.jobs (run_after ASC) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS jobs_stuck_idx ON public.jobs (locked_at ASC) WHERE status = 'running';
CREATE INDEX IF NOT EXISTS jobs_meeting_idx ON public.jobs (meeting_id);

-- 14. App Settings Table
CREATE TABLE IF NOT EXISTS public.app_settings (
  key         TEXT PRIMARY KEY,
  value       JSONB NOT NULL,
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_by  UUID REFERENCES auth.users (id) ON DELETE SET NULL
);

-- 15. Audit Logs Table
CREATE TABLE IF NOT EXISTS public.audit_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id    UUID REFERENCES auth.users (id) ON DELETE SET NULL,
  actor_email TEXT,
  action      TEXT NOT NULL,
  target_type TEXT,
  target_id   TEXT,
  metadata    JSONB DEFAULT '{}'::jsonb,
  ip_address  TEXT,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON public.audit_logs (action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_target ON public.audit_logs (target_type, target_id);
