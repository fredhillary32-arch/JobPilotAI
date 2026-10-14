from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

ExtractionStatus = Literal["succeeded", "no_text", "failed"]
ExtractionErrorCategory = Literal[
    "missing_file",
    "invalid_document",
    "encrypted_document",
    "resource_limit",
    "unsupported_content",
    "decoding_error",
    "extraction_error",
]


class DocumentExtractionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_document_id: UUID
    status: ExtractionStatus
    character_count: int
    extractor_version: str
    error_category: ExtractionErrorCategory | None
    extracted_at: datetime
    trust_status: Literal["unverified_source_text"] = "unverified_source_text"


class ExtractedTextRead(BaseModel):
    source_document_id: UUID
    status: ExtractionStatus
    text: str | None
    character_count: int
    trust_status: Literal["unverified_source_text"] = "unverified_source_text"
    note: str = "Extracted text is untrusted source content, not verified candidate evidence."
