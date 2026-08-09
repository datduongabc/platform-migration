import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.services.quota import (
    QuotaMovementParams,
    QuotaMovementResult,
    apply_quota_movement,
)


def make_db_returning_row(row: dict):
    db = MagicMock()
    result = MagicMock()
    result.mappings.return_value.first.return_value = row
    db.execute = AsyncMock(return_value=result)
    return db


def base_params(**overrides):
    defaults = dict(
        user_id="11111111-1111-1111-1111-111111111111",
        delta_audio_seconds=-10,
        delta_agent_queries=0,
        reason="generate",
        dedup_key="test:dedup",
        allow_overdraw=False,
    )
    defaults.update(overrides)
    return QuotaMovementParams(**defaults)


def test_apply_quota_movement_reads_correct_row_keys():
    # Regression test for a real bug found in this codebase: the RPC's
    # RETURNS TABLE columns are audio_seconds_remaining/agent_queries_remaining
    # (see migrations/003_functions_and_triggers.sql), not audio_remaining/
    # agent_remaining. Reading the wrong keys previously raised a KeyError on
    # every single successful call, which was masked by a blanket except-and-
    # fabricate-success fallback that has since been removed — so if this
    # regresses, the call now raises instead of silently faking a result.
    db = make_db_returning_row(
        {"status": "ok", "audio_seconds_remaining": 3590, "agent_queries_remaining": 99}
    )

    result = asyncio.run(apply_quota_movement(db, base_params()))

    assert isinstance(result, QuotaMovementResult)
    assert result.status == "ok"
    assert result.audio_remaining == 3590
    assert result.agent_remaining == 99
    assert isinstance(result.audio_remaining, int)


def test_apply_quota_movement_normalizes_already_processed_status():
    # The SQL function's dedup-hit branch returns 'already_processed', but the
    # Python status literal is 'already_applied' — this mapping must happen
    # here, not be left as a landmine for whoever branches on the raw string.
    db = make_db_returning_row(
        {"status": "already_processed", "audio_seconds_remaining": 100, "agent_queries_remaining": 5}
    )

    result = asyncio.run(apply_quota_movement(db, base_params()))

    assert result.status == "already_applied"


def test_apply_quota_movement_insufficient_status_passthrough():
    db = make_db_returning_row(
        {"status": "insufficient", "audio_seconds_remaining": 0, "agent_queries_remaining": 0}
    )

    result = asyncio.run(apply_quota_movement(db, base_params()))

    assert result.status == "insufficient"


def test_apply_quota_movement_propagates_db_errors_instead_of_fabricating_success():
    # Regression test: this used to catch ANY exception and return a fabricated
    # status="applied" with a 99999/999 balance — silently disabling quota
    # enforcement on any transient DB error. It must now propagate.
    db = MagicMock()
    db.execute = AsyncMock(side_effect=RuntimeError("connection reset"))

    with pytest.raises(RuntimeError):
        asyncio.run(apply_quota_movement(db, base_params()))
