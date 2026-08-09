import asyncio
import json
import logging
import os
import urllib.parse
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.repositories.project import ProjectRepository
from app.schemas.codegen import ProjectResponse
from app.schemas.meeting import (
    CalendarSuggestionUpdateRequest,
    MeetingCreateRequest,
    MeetingCreateResponse,
    MeetingDetailResponse,
    MeetingUpdateRequest,
    TodoUpdateRequest,
)
from app.services.access import check_folder_access, check_meeting_access
from app.services.ai.resolve import resolve_generation_model
from app.services.audio import extract_audio_from_video, probe_streams
from app.services.gemini import analyze_transcript
from app.services.ics import build_ics
from app.services.storage import (
    generate_r2_presigned_upload_url,
    get_active_storage_credentials,
)
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
router = APIRouter()


ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".webm"}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
MAX_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB


def format_meeting_title(dt: datetime) -> str:
    # Next.js format: e.g. "Aug 7, 2026, 11:30 AM"
    return dt.strftime("%b %d, %Y, %I:%M %p")


async def enqueue_job(db: AsyncSession, meeting_id: UUID, payload: dict = None):
    job_id = uuid.uuid4()
    await db.execute(
        text("""
            INSERT INTO public.jobs (id, meeting_id, step, status, run_after, payload, created_at, updated_at)
            VALUES (:id, :meeting_id, 'start', 'queued', NOW(), :payload, NOW(), NOW())
        """),
        {
            "id": job_id,
            "meeting_id": meeting_id,
            "payload": json.dumps(payload or {}),
        },
    )
    await db.commit()


@router.get("/projects", response_model=List[ProjectResponse])
async def list_user_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the list of projects (meetings) belonging to the authenticated user.
    """
    projects = await ProjectRepository.list_user_projects(
        db, current_user.id, skip, limit
    )
    return projects


@router.post("/meetings", response_model=MeetingCreateResponse)
async def create_meeting(
    payload: MeetingCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Creates a meeting row in the database and returns a local upload URL or Presigned R2 URL.
    """
    meeting_id = uuid.uuid4()

    # Parse start date
    started_at_dt = None
    if payload.startedAt:
        try:
            # Parse ISO-8601 string
            started_at_dt = datetime.fromisoformat(
                payload.startedAt.replace("Z", "+00:00")
            )
        except Exception:
            pass

    if not started_at_dt:
        started_at_dt = datetime.utcnow()

    title = format_meeting_title(started_at_dt)

    ext = (payload.fileExtension or ".webm").lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    is_video = ext in ALLOWED_VIDEO_EXTENSIONS
    if ext not in ALLOWED_AUDIO_EXTENSIONS and not is_video:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file extension '{ext}'. Allowed: "
            f"{', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS))}.",
        )

    # Relative path on disk / object key
    audio_path = f"uploads/{current_user.id}/{meeting_id}{ext}"

    # Check if active R2 credentials exist
    active_storage = await get_active_storage_credentials(db)
    upload_url = None

    if active_storage:
        presigned = generate_r2_presigned_upload_url(
            account_id=active_storage["account_id"],
            access_key_id=active_storage["access_key_id"],
            secret_access_key=active_storage["secret_access_key"],
            bucket=active_storage["bucket"],
            object_key=audio_path,
            content_type=payload.mimeType or "audio/webm",
        )
        if presigned:
            upload_url = presigned

    # Fallback to local server upload endpoint
    if not upload_url:
        upload_url = f"{request.base_url}api/v1/meetings/{meeting_id}/upload-file"

    # Assigning into a folder at create time requires editor+ access to it, same
    # as moving an existing meeting there (see update_meeting). 404 rather than 403
    # so a probe for another user's folder id doesn't confirm its existence.
    if payload.folderId is not None:
        if not await check_folder_access(
            db, payload.folderId, current_user.id, "editor"
        ):
            raise HTTPException(status_code=404, detail="Folder not found")

    # Save project to DB
    await ProjectRepository.create(
        db=db,
        project_id=meeting_id,
        user_id=current_user.id,
        title=title,
        audio_path=audio_path,
        duration_seconds=payload.durationSeconds,
        started_at=started_at_dt,
        source="video" if is_video else (payload.source or "recorded"),
        storage_provider="r2",
        folder_id=payload.folderId,
    )
    await db.commit()

    return MeetingCreateResponse(
        meetingId=meeting_id,
        uploadUrl=upload_url,
        contentType=payload.mimeType or "audio/webm",
    )


@router.put("/meetings/{id}/upload-file")
async def upload_meeting_file(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    PUT endpoint to upload the raw binary file for a meeting.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Read the raw request body
    body = await request.body()
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=422,
            detail=f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024*1024)} GiB upload limit.",
        )

    # Save locally to uploads/user_id/meeting_id.ext
    user_dir = os.path.join("uploads", str(current_user.id))
    os.makedirs(user_dir, exist_ok=True)

    # Extract file extension
    ext = os.path.splitext(project.audio_path)[1] if project.audio_path else ".webm"
    file_path = os.path.join(user_dir, f"{id}{ext}")

    def _write_file():
        with open(file_path, "wb") as f:
            f.write(body)

    await asyncio.to_thread(_write_file)

    # Update audio_path to local path
    project.audio_path = file_path
    await db.commit()

    return {"ok": True}


@router.post("/meetings/{id}/uploaded")
async def confirm_uploaded(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Confirm file upload completed, validate it, extract audio from video uploads,
    and enqueue the processing job.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    async def _reject(detail: str):
        # Mirrors ricotdin's rejectUpload: never leave an orphaned pending meeting
        # row (or its file) behind after a validation failure.
        if project.audio_path and os.path.exists(project.audio_path):
            try:
                os.remove(project.audio_path)
            except Exception:
                pass
        await ProjectRepository.delete(db, project)
        await db.commit()
        raise HTTPException(status_code=422, detail=detail)

    if not project.audio_path or not os.path.exists(project.audio_path):
        # File may legitimately live on R2 instead of local disk — only enforce
        # existence for the local-disk path this deployment primarily uses.
        if project.storage_provider != "r2":
            await _reject("Upload may have failed: audio file not found on disk.")
    else:
        size = os.path.getsize(project.audio_path)
        if size > MAX_UPLOAD_BYTES:
            await _reject(
                f"File exceeds the {MAX_UPLOAD_BYTES // (1024*1024*1024)} GiB upload limit."
            )
        elif size == 0:
            await _reject("Uploaded file is empty.")
        else:
            streams = await probe_streams(project.audio_path)
            if project.source == "video":
                if not streams["has_audio"]:
                    await _reject("Video file has no audio track.")
                else:
                    # Extract audio-only mp3, replace audio_path, drop the original video.
                    base, _ = os.path.splitext(project.audio_path)
                    mp3_path = f"{base}.mp3"
                    ok = await extract_audio_from_video(project.audio_path, mp3_path)
                    if ok:
                        original_video_path = project.audio_path
                        project.audio_path = mp3_path
                        await db.commit()
                        try:
                            os.remove(original_video_path)
                        except Exception:
                            pass
                    # If extraction fails (e.g. ffmpeg unavailable), fall through and
                    # let the pipeline attempt the original file directly rather than
                    # hard-failing the whole upload.
            else:
                if streams["has_video"]:
                    await _reject(
                        "This looks like a video file — please use the video upload flow."
                    )
                elif not streams["has_audio"]:
                    await _reject("File has no audio track.")

    # Enqueue job
    await enqueue_job(db, id)
    return {"ok": True, "meetingId": str(id)}


@router.get("/meetings/{id}", response_model=MeetingDetailResponse)
async def get_meeting_detail(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retrieve full meeting details (segments, todos, calendar suggestions).
    """
    project = await ProjectRepository.get_by_id_with_relations(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await check_meeting_access(db, project, current_user.id, "viewer"):
        raise HTTPException(status_code=403, detail="Forbidden")

    return project


MAX_TITLE_LEN = 200


@router.patch("/meetings/{id}")
async def update_meeting(
    id: UUID,
    payload: MeetingUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Rename a meeting or move it to a folder. Editor+ access is sufficient
    (owner, folder owner, or folder editor share) — stricter than viewer,
    looser than delete's owner-only rule.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        logger.warning(
            f"[update_meeting] Meeting ID {id} not found in database for user {current_user.id}"
        )
        raise HTTPException(
            status_code=404, detail=f"Meeting {id} not found in database"
        )
    if not await check_meeting_access(db, project, current_user.id, "editor"):
        raise HTTPException(status_code=403, detail="Forbidden")

    fields_set = payload.model_fields_set
    if "title" not in fields_set and "folder_id" not in fields_set:
        raise HTTPException(status_code=422, detail="No updatable fields provided.")

    if "title" in fields_set and payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=422, detail="Title cannot be empty")
        if len(title) > MAX_TITLE_LEN:
            raise HTTPException(
                status_code=422, detail=f"Title must be at most {MAX_TITLE_LEN} characters."
            )
        project.title = title

    if "folder_id" in fields_set:
        # Moving into a folder requires editor+ on the DESTINATION folder too —
        # otherwise a user could assign their own meeting into someone else's
        # folder without that folder's owner ever granting access.
        if payload.folder_id is not None:
            if not await check_folder_access(
                db, payload.folder_id, current_user.id, "editor"
            ):
                raise HTTPException(status_code=404, detail="Folder not found")
        project.folder_id = payload.folder_id

    project.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "title": project.title, "folder_id": project.folder_id}


@router.patch("/meetings/{id}/pin")
async def pin_meeting(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Toggle pin status of a meeting.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if project.pinned_at is None:
        project.pinned_at = datetime.utcnow()
    else:
        project.pinned_at = None

    project.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True, "pinned": project.pinned_at is not None}


@router.delete("/meetings/{id}")
async def delete_meeting(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Deletes meeting row + audio file from local disk.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    # Clean up local file
    if project.audio_path and os.path.exists(project.audio_path):
        try:
            os.remove(project.audio_path)
        except Exception as e:
            logger.warning(f"Failed to delete local audio: {e}")

    await ProjectRepository.delete(db, project)
    await db.commit()
    return {"ok": True}


@router.get("/audio-url/{id}")
async def get_audio_url(
    id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generates download / streaming URL for the meeting audio.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Viewer+ is sufficient — this is the only sanctioned way the browser gets a
    # playback URL, so a shared-folder viewer must be able to call it.
    if not await check_meeting_access(db, project, current_user.id, "viewer"):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not project.audio_path:
        raise HTTPException(status_code=404, detail="Audio file path missing")

    # Check candidate local paths
    candidates = [
        project.audio_path,
        os.path.join(".", project.audio_path),
        os.path.join("uploads", project.audio_path),
        os.path.join("uploads", project.audio_path.replace("recordings/", "")),
    ]
    for cand in candidates:
        if os.path.exists(cand):
            rel_path = os.path.normpath(cand).replace("\\", "/")
            if rel_path.startswith("uploads/"):
                url = f"{request.base_url}{rel_path}"
            else:
                url = f"{request.base_url}uploads/{rel_path}"
            return {"url": url}

    # If it is a Supabase legacy path, redirect/point to the Supabase storage public bucket
    # We parse the database project reference from DATABASE_URL
    project_ref = None
    if (
        "supabase.com" in settings.DATABASE_URL
        or "supabase.co" in settings.DATABASE_URL
    ):
        try:
            import urllib.parse

            parsed = urllib.parse.urlparse(settings.DATABASE_URL)
            username = parsed.username
            if username and "postgres." in username:
                project_ref = username.split("postgres.")[1]
        except Exception:
            pass

    if project_ref:
        path_clean = project.audio_path
        if path_clean.startswith("recordings/"):
            path_clean = path_clean[len("recordings/") :]
        import urllib.parse

        encoded_path = urllib.parse.quote(path_clean)
        supabase_url = f"https://{project_ref}.supabase.co/storage/v1/object/public/recordings/{encoded_path}"
        return {"url": supabase_url}

    raise HTTPException(status_code=404, detail="Audio file not found")


@router.post("/meetings/{id}/process")
async def process_meeting(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    User-facing (re)process trigger. Deliberately thin and idempotent: it only
    enqueues a job — the actual claim guard (status IN ('pending','failed')) lives
    in the job's 'start' step, so calling this on an already processing/done
    meeting is a safe no-op rather than destroying existing results. The
    destructive reset-and-requeue variant is admin-only, see
    POST /admin/pipeline/{id}/requeue, and is gated to failed/stuck meetings there.
    """
    project = await ProjectRepository.get_by_id(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    await enqueue_job(db, id)
    return {"ok": True, "meetingId": str(id), "status": "processing"}


@router.post("/meetings/{id}/regenerate")
async def regenerate_meeting_analysis(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Re-run Gemini analysis for structured notes, summary, and action items.
    """
    project = await ProjectRepository.get_by_id_with_relations(db, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if project.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not project.segments:
        raise HTTPException(
            status_code=422, detail="No transcript available to analyze."
        )

    # Format segments for the Gemini API call
    segments_payload = [
        {
            "speaker": seg.speaker or "Speaker",
            "start_ms": seg.start_ms,
            "end_ms": seg.end_ms,
            "text": seg.text,
            "confidence": seg.confidence or 1.0,
        }
        for seg in project.segments
    ]

    started_at_str = project.started_at.isoformat() if project.started_at else None
    _, resolved_model = await resolve_generation_model(
        db, user_id=str(project.user_id)
    )

    # Run Gemini Analysis
    try:
        analysis = await analyze_transcript(
            segments_payload, meeting_date=started_at_str, model=resolved_model
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini analysis failed: {str(e)}")

    # Update meeting row. A successful regenerate clears any prior failed state —
    # e.g. a meeting that failed after transcription but before analysis, then had
    # segments already present, could otherwise stay stuck 'failed' in the UI even
    # after this endpoint successfully re-analyzed it.
    project.summary = analysis.summary
    project.notes = analysis.notes_markdown
    project.status = "done"
    project.error_message = None
    project.updated_at = datetime.utcnow()

    # Clear old todos and suggestions
    await db.execute(
        text("DELETE FROM public.todos WHERE meeting_id = :id"), {"id": id}
    )
    await db.execute(
        text("DELETE FROM public.calendar_suggestions WHERE meeting_id = :id"),
        {"id": id},
    )
    await db.commit()

    segment_id_by_index = {seg.segment_index: seg.id for seg in project.segments}

    # Insert new todos
    for todo in analysis.todos:
        source_id = None
        if todo.source_segment_index is not None:
            source_id = segment_id_by_index.get(todo.source_segment_index)

        await db.execute(
            text("""
                INSERT INTO public.todos (id, meeting_id, content, assignee, due_date, status, source_segment_id, created_at, updated_at)
                VALUES (:id, :meeting_id, :content, :assignee, :due_date, 'open', :source_segment_id, NOW(), NOW())
            """),
            {
                "id": uuid.uuid4(),
                "meeting_id": id,
                "content": todo.content,
                "assignee": todo.assignee,
                "due_date": todo.due_date,
                "source_segment_id": source_id,
            },
        )

    # Insert new suggestions
    for sug in analysis.calendar_suggestions:
        source_id = None
        if sug.source_segment_index is not None:
            source_id = segment_id_by_index.get(sug.source_segment_index)

        await db.execute(
            text("""
                INSERT INTO public.calendar_suggestions (id, meeting_id, title, proposed_at, raw_mention, dismissed, source_segment_id, created_at)
                VALUES (:id, :meeting_id, :title, :proposed_at, :raw_mention, FALSE, :source_segment_id, NOW())
            """),
            {
                "id": uuid.uuid4(),
                "meeting_id": id,
                "title": sug.title,
                "proposed_at": sug.proposed_at,
                "raw_mention": sug.raw_mention,
                "source_segment_id": source_id,
            },
        )

    await db.commit()
    return {"ok": True, "summary": project.summary, "notes": project.notes}


@router.patch("/todos/{id}")
async def update_todo(
    id: UUID,
    payload: TodoUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Update todo status (open, done, dismissed).
    """
    todo = await ProjectRepository.get_todo_by_id(db, id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    meeting = await ProjectRepository.get_by_id(db, todo.meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await check_meeting_access(db, meeting, current_user.id, "editor"):
        raise HTTPException(status_code=403, detail="Forbidden")

    todo.status = payload.status
    todo.updated_at = datetime.utcnow()
    await db.commit()
    return {"ok": True}


@router.patch("/calendar-suggestions/{id}")
async def update_calendar_suggestion(
    id: UUID,
    payload: CalendarSuggestionUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Dismiss calendar suggestions.
    """
    sug = await ProjectRepository.get_calendar_suggestion_by_id(db, id)
    if not sug:
        raise HTTPException(status_code=404, detail="Calendar suggestion not found")

    meeting = await ProjectRepository.get_by_id(db, sug.meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await check_meeting_access(db, meeting, current_user.id, "editor"):
        raise HTTPException(status_code=403, detail="Forbidden")

    sug.dismissed = payload.dismissed
    await db.commit()
    return {"ok": True}


@router.get("/calendar-suggestions/{id}/ics")
async def download_calendar_suggestion_ics(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Downloads raw .ics calendar invite for a meeting calendar suggestion.
    """
    sug = await ProjectRepository.get_calendar_suggestion_by_id(db, id)
    if not sug:
        raise HTTPException(status_code=404, detail="Calendar suggestion not found")

    meeting = await ProjectRepository.get_by_id(db, sug.meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    # Downloading a calendar file is read-only in effect — viewer+ is sufficient,
    # matching the (weaker) requirement vs. the editor+ dismiss endpoint above.
    if not await check_meeting_access(db, meeting, current_user.id, "viewer"):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not sug.proposed_at:
        raise HTTPException(
            status_code=422, detail="Vague proposed date, cannot generate .ics file"
        )

    ics_content = build_ics(
        uid=f"{sug.id}@ricotdin",
        summary=sug.title,
        dtstart=sug.proposed_at,
        dtstamp=datetime.utcnow(),
        description=f'Auto-generated suggestion from meeting: {meeting.title}. Phrasing: "{sug.raw_mention}"',
    )

    # Return as raw response attachment
    return Response(
        content=ics_content,
        media_type="text/calendar",
        headers={"Content-Disposition": f"attachment; filename=event-{sug.id}.ics"},
    )


# Only these are legitimate for a client to self-report. Server-side lifecycle
# events (login, meeting_created, processing_done, ...) are written directly by
# their own endpoints/pipeline steps — never accept them from this client-facing
# route, or any caller could forge an arbitrary activity trail for themselves.
CLIENT_EVENT_TYPES = {"record_start", "record_stop"}


class ActivityLogRequest(BaseModel):
    eventType: str
    userId: UUID
    meetingId: Optional[UUID] = None


@router.post("/activity")
async def log_activity(
    payload: ActivityLogRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Log client recording events (record_start, record_stop).
    """
    if payload.userId != current_user.id:
        raise HTTPException(
            status_code=403, detail="Forbidden: userId must match authenticated user"
        )

    if payload.eventType not in CLIENT_EVENT_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"eventType must be one of: {', '.join(sorted(CLIENT_EVENT_TYPES))}",
        )

    try:
        await db.execute(
            text("""
                INSERT INTO public.activity_log (id, user_id, event_type, meeting_id, created_at)
                VALUES (:id, :user_id, :event_type, :meeting_id, NOW())
            """),
            {
                "id": uuid.uuid4(),
                "user_id": current_user.id,
                "event_type": payload.eventType,
                "meeting_id": payload.meetingId,
            },
        )
        await db.commit()
    except Exception:
        pass

    return {"ok": True}


@router.get("/calendar-suggestions/{id}/gcal-link")
async def get_gcal_event_link(
    id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generates a 1-click Google Calendar web event creation URL for a calendar suggestion.
    """
    sug = await ProjectRepository.get_calendar_suggestion_by_id(db, id)
    if not sug:
        raise HTTPException(status_code=404, detail="Calendar suggestion not found")

    meeting = await ProjectRepository.get_by_id(db, sug.meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    if not await check_meeting_access(db, meeting, current_user.id, "viewer"):
        raise HTTPException(status_code=403, detail="Forbidden")

    if not sug.proposed_at:
        raise HTTPException(
            status_code=422, detail="Vague proposed date, cannot generate calendar link"
        )

    start_dt = sug.proposed_at
    end_dt = start_dt + timedelta(hours=1)

    start_str = start_dt.strftime("%Y%m%dT%H%M%SZ")
    end_str = end_dt.strftime("%Y%m%dT%H%M%SZ")

    title_encoded = urllib.parse.quote(sug.title)
    desc_encoded = urllib.parse.quote(
        f'Generated from meeting: {meeting.title}\nRaw mention: "{sug.raw_mention}"'
    )

    gcal_url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={title_encoded}&details={desc_encoded}&dates={start_str}/{end_str}"

    return {"gcalUrl": gcal_url}
