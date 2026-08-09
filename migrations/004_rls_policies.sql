-- ============================================================================
-- Migration 004: Row Level Security (RLS) Policies and Access Privileges
-- Target: Clean owner-based security with folder sharing & admin overrides
-- ============================================================================

-- 1. Enable RLS on all tables
ALTER TABLE public.profiles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.meetings             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transcript_segments  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.transcript_chunks    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.todos                ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calendar_suggestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.folders               ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.folder_shares        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages        ENABLE ROW LEVEL SECURITY;

-- 2. Helper function to check meeting access (Owner OR shared folder)
CREATE OR REPLACE FUNCTION public.check_meeting_access(
  p_meeting_id UUID,
  p_user_id    UUID
)
RETURNS BOOLEAN
LANGUAGE sql
STABLE SECURITY DEFINER SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.meetings m
    WHERE m.id = p_meeting_id
      AND (
        m.user_id = p_user_id
        OR EXISTS (
          SELECT 1 FROM public.folder_shares fs
          WHERE fs.folder_id = m.folder_id
            AND fs.user_id = p_user_id
        )
      )
  );
$$;

-- 3. Profiles Policies
DROP POLICY IF EXISTS "Public profiles are viewable by owner or admin" ON public.profiles;
CREATE POLICY "Public profiles are viewable by owner or admin"
  ON public.profiles FOR SELECT
  USING (auth.uid() = id OR (auth.jwt()->>'role') = 'admin');

DROP POLICY IF EXISTS "Users can update own profile" ON public.profiles;
CREATE POLICY "Users can update own profile"
  ON public.profiles FOR UPDATE
  USING (auth.uid() = id)
  WITH CHECK (auth.uid() = id);

-- 4. Meetings Policies
DROP POLICY IF EXISTS "Users can view own or shared meetings" ON public.meetings;
CREATE POLICY "Users can view own or shared meetings"
  ON public.meetings FOR SELECT
  USING (check_meeting_access(id, auth.uid()));

DROP POLICY IF EXISTS "Users can insert own meetings" ON public.meetings;
CREATE POLICY "Users can insert own meetings"
  ON public.meetings FOR INSERT
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own or shared editable meetings" ON public.meetings;
CREATE POLICY "Users can update own or shared editable meetings"
  ON public.meetings FOR UPDATE
  USING (check_meeting_access(id, auth.uid()));

DROP POLICY IF EXISTS "Users can delete own meetings" ON public.meetings;
CREATE POLICY "Users can delete own meetings"
  ON public.meetings FOR DELETE
  USING (auth.uid() = user_id);

-- 5. Child Tables Policies (Segments, Chunks, Todos, Calendar Mentions)
DROP POLICY IF EXISTS "Access transcript_segments" ON public.transcript_segments;
CREATE POLICY "Access transcript_segments"
  ON public.transcript_segments FOR ALL
  USING (check_meeting_access(meeting_id, auth.uid()));

DROP POLICY IF EXISTS "Access transcript_chunks" ON public.transcript_chunks;
CREATE POLICY "Access transcript_chunks"
  ON public.transcript_chunks FOR ALL
  USING (check_meeting_access(meeting_id, auth.uid()));

DROP POLICY IF EXISTS "Access todos" ON public.todos;
CREATE POLICY "Access todos"
  ON public.todos FOR ALL
  USING (check_meeting_access(meeting_id, auth.uid()));

DROP POLICY IF EXISTS "Access calendar_suggestions" ON public.calendar_suggestions;
CREATE POLICY "Access calendar_suggestions"
  ON public.calendar_suggestions FOR ALL
  USING (check_meeting_access(meeting_id, auth.uid()));

-- 6. Folders Policies
DROP POLICY IF EXISTS "Own folders" ON public.folders;
CREATE POLICY "Own folders"
  ON public.folders FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Own folder_shares" ON public.folder_shares;
CREATE POLICY "Own folder_shares"
  ON public.folder_shares FOR ALL
  USING (auth.uid() = user_id OR EXISTS (SELECT 1 FROM public.folders f WHERE f.id = folder_id AND f.user_id = auth.uid()));

-- 7. Chat Sessions & Messages Policies
DROP POLICY IF EXISTS "Own chat_sessions" ON public.chat_sessions;
CREATE POLICY "Own chat_sessions"
  ON public.chat_sessions FOR ALL
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Own chat_messages" ON public.chat_messages;
CREATE POLICY "Own chat_messages"
  ON public.chat_messages FOR ALL
  USING (EXISTS (SELECT 1 FROM public.chat_sessions s WHERE s.id = session_id AND s.user_id = auth.uid()));
