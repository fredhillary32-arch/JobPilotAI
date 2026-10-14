from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

CvExportFormat = Literal["pdf", "docx"]


class TailoredCvExportCreate(BaseModel):
    export_format: CvExportFormat


class TailoredCvExportRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    cv_draft_id: UUID
    document_id: UUID
    export_format: CvExportFormat
    page_count: int | None
    filename: str
    media_type: str
    size_bytes: int
    created_at: datetime
