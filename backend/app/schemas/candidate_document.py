from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

DocumentKind = Literal["source_cv", "supporting_document"]


class CandidateDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    candidate_profile_id: UUID
    source_document_id: UUID | None
    document_kind: str
    provenance: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256: str
    target_job_title: str | None
    target_company: str | None
    created_at: datetime
