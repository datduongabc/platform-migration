import json
import logging
import uuid
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def write_audit_log(
    db: AsyncSession,
    actor_id: uuid.UUID | str,
    actor_email: str,
    action: str,
    target_type: str,
    target_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Inserts a row into public.audit_logs. Fire-and-forget by design (mirrors
    ricotdin's writeAuditLog): a logging failure must never surface to the caller
    or roll back the real mutation it's describing, so every error is swallowed
    here after being logged.
    """
    sql = text("""
        INSERT INTO public.audit_logs (
            id, created_at, actor_id, actor_email, action, target_type, target_id, metadata, ip_address, user_agent
        ) VALUES (
            :id, NOW(), :actor_id, :actor_email, :action, :target_type, :target_id, :metadata, :ip_address, :user_agent
        )
    """)
    try:
        await db.execute(
            sql,
            {
                "id": uuid.uuid4(),
                "actor_id": actor_id,
                "actor_email": actor_email,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "metadata": json.dumps(metadata or {}),
                "ip_address": ip_address,
                "user_agent": user_agent,
            },
        )
    except Exception as e:
        logger.warning(f"[audit] write_audit_log failed for action={action!r}: {e}")
