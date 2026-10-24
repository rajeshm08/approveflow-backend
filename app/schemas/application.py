from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApplicationCreate(BaseModel):
    program_name: str = Field(min_length=2, max_length=200)
    application_type: str = Field(default="new_approval", max_length=80)
    workflow_template_id: int | None = None


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application_id: int
    application_number: str
    institution_id: int
    institution_name: str
    program_name: str
    application_type: str
    current_stage: str
    status: str
    due_at: datetime | None
    created_at: datetime
    updated_at: datetime


class TransitionRequest(BaseModel):
    expected_current_stage: str = Field(min_length=1, max_length=60)
    next_stage: str = Field(min_length=1, max_length=60)
    reason: str = Field(min_length=1, max_length=2000)


class SubmitRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class TimelineEntry(BaseModel):
    id: int
    application_id: int
    from_stage: str | None
    to_stage: str
    status: str
    reason: str | None
    actor_id: int
    created_at: datetime
