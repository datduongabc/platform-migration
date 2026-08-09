-- ============================================================================
-- Migration 001: Extensions, Enums, and Shared Utility Functions
-- Target: PostgreSQL 15+ with pgvector
-- ============================================================================

-- 1. Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "vector";     -- pgvector for vector embeddings

-- 2. Auth Schema & Auth Users table (for standalone & Supabase migration compatibility)
CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE IF NOT EXISTS auth.users (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email               TEXT UNIQUE,
  encrypted_password  TEXT,
  raw_user_meta_data  JSONB DEFAULT '{}'::jsonb,
  disabled_at         TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fallback auth helper functions for standalone PostgreSQL
CREATE OR REPLACE FUNCTION auth.uid()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
  SELECT NULL::UUID;
$$;

CREATE OR REPLACE FUNCTION auth.jwt()
RETURNS JSONB
LANGUAGE sql
STABLE
AS $$
  SELECT '{}'::jsonb;
$$;

-- 2. Enums (Using DO blocks to prevent errors if type already exists)
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'meeting_status') THEN
    CREATE TYPE meeting_status AS ENUM ('pending', 'processing', 'done', 'failed');
  END IF;
  
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'todo_status') THEN
    CREATE TYPE todo_status AS ENUM ('open', 'done', 'dismissed');
  END IF;
  
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chat_role') THEN
    CREATE TYPE chat_role AS ENUM ('user', 'assistant');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'folder_role') THEN
    CREATE TYPE folder_role AS ENUM ('viewer', 'editor');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'activity_log_level') THEN
    CREATE TYPE activity_log_level AS ENUM ('info', 'warn', 'error');
  END IF;
END $$;

-- 3. Shared Trigger Function: Automatic updated_at timestamp manager
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$;
