from datetime import datetime
from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class PipelineCounts(BaseModel):
    pending: int
    processing: int
    done: int
    failed: int
    stuck: int


class PipelineOverviewResponse(BaseModel):
    counts: PipelineCounts
    avg_processing_secs: Optional[int] = None
    stuck_threshold_minutes: int
    total: int


class PipelineJob(BaseModel):
    id: UUID
    title: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    duration_seconds: Optional[int] = None
    error_message: Optional[str] = None
    owner_email: Optional[str] = None
    owner_username: Optional[str] = None
    is_stuck: bool


class PipelineJobsResponse(BaseModel):
    jobs: List[PipelineJob]
    total: int
    page: int
    perPage: int


class KeyResponse(BaseModel):
    id: UUID
    created_at: datetime
    updated_at: Optional[datetime] = None
    config_key: str
    label: str
    last4: str
    status: str
    disabled_reason: Optional[str] = None
    last_used_at: Optional[datetime] = None
    health_status: Optional[str] = "unknown"
    health_checked_at: Optional[str] = None
    health_detail: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class KeyListResponse(BaseModel):
    keys: List[KeyResponse]
    healthColumnsMissing: bool = False


class KeyCreateRequest(BaseModel):
    configKey: str
    label: str
    key: str


class KeyUpdateRequest(BaseModel):
    status: str
    disabled_reason: Optional[str] = None


class HealthProbeInfo(BaseModel):
    id: UUID
    config_key: str
    label: str
    status: str
    detail: Optional[str] = None


class HealthCheckResponse(BaseModel):
    ranAt: str
    summary: dict
    keys: List[HealthProbeInfo]
