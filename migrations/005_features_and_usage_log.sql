-- ============================================================================
-- Migration 005: Feature Registry columns + AI Usage Log table
-- ============================================================================
-- Fixes two latent bugs where app/api/endpoints/admin/{features,audit}.py query
-- columns/tables that were never created by an earlier migration:
--   - public.features was created (002) as a bare feature-flag table
--     (id/key/enabled/description/updated_at), but the admin Feature Registry
--     endpoint (ricotdin Phase 15 parity) expects the full registry schema.
--   - public.usage_log never existed at all; GET /admin/ai-usage 500'd
--     unconditionally.
-- ============================================================================

-- 1. Extend public.features to the full registry schema (ricotdin migrations/017_features.sql).
ALTER TABLE public.features
  ADD COLUMN IF NOT EXISTS created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS updated_by    TEXT,
  ADD COLUMN IF NOT EXISTS source_path   TEXT,
  ADD COLUMN IF NOT EXISTS module_prefix TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS module_name   TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS title         TEXT NOT NULL DEFAULT '',
  ADD COLUMN IF NOT EXISTS user_story    TEXT,
  ADD COLUMN IF NOT EXISTS content       TEXT,
  ADD COLUMN IF NOT EXISTS status        TEXT NOT NULL DEFAULT 'not_started',
  ADD COLUMN IF NOT EXISTS priority      TEXT,
  ADD COLUMN IF NOT EXISTS note_tags     TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS depends_on    TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS blocks        TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS key_files     TEXT[] NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS metadata      JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN IF NOT EXISTS change_note   TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'features_status_check'
  ) THEN
    ALTER TABLE public.features
      ADD CONSTRAINT features_status_check
      CHECK (status IN ('done', 'partial', 'not_started'));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'features_priority_check'
  ) THEN
    ALTER TABLE public.features
      ADD CONSTRAINT features_priority_check
      CHECK (priority IS NULL OR priority IN ('high', 'medium', 'low'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS features_module_prefix_idx ON public.features (module_prefix);
CREATE INDEX IF NOT EXISTS features_status_idx        ON public.features (status);

DROP TRIGGER IF EXISTS trg_features_updated_at ON public.features;
CREATE TRIGGER trg_features_updated_at
  BEFORE UPDATE ON public.features
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 2. AI Provider Usage Log (ricotdin migrations/009_usage_log.sql + 019_usage_log_key.sql).
-- unit-aware: 'unit' names the primary metering unit for the row ('tokens' |
-- 'audio_seconds') and 'quantity' holds the value in that unit — NEVER aggregate
-- quantity across different units, they are incommensurable (see admin/audit.py's
-- get_ai_usage_telemetry, which already groups by unit for this reason).
CREATE TABLE IF NOT EXISTS public.usage_log (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  provider       TEXT NOT NULL,
  model          TEXT NOT NULL,
  operation      TEXT NOT NULL,

  input_tokens   INTEGER NULL,
  output_tokens  INTEGER NULL,
  total_tokens   INTEGER NULL,

  audio_seconds  NUMERIC NULL,

  unit           TEXT NOT NULL CHECK (unit IN ('tokens', 'audio_seconds')),
  quantity       NUMERIC NOT NULL,

  status         TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'rate_limited', 'error')),
  http_code      INTEGER NULL,

  meeting_id     UUID NULL REFERENCES public.meetings (id) ON DELETE SET NULL,
  user_id        UUID NULL REFERENCES auth.users (id) ON DELETE SET NULL,
  key_id         UUID NULL REFERENCES public.admin_config (id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS usage_log_created_at_idx ON public.usage_log (created_at DESC);
CREATE INDEX IF NOT EXISTS usage_log_provider_idx   ON public.usage_log (provider, model);
CREATE INDEX IF NOT EXISTS usage_log_operation_idx  ON public.usage_log (operation);
CREATE INDEX IF NOT EXISTS usage_log_meeting_id_idx ON public.usage_log (meeting_id) WHERE meeting_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS usage_log_status_idx     ON public.usage_log (status) WHERE status != 'ok';
CREATE INDEX IF NOT EXISTS usage_log_key_id_idx     ON public.usage_log (key_id) WHERE key_id IS NOT NULL;
