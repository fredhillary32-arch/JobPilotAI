"""Whether evidence still matches its source document's current extracted text.

Re-extraction replaces a document's single extraction row. Evidence stores the
exact excerpt and offsets it was created from, so it stays *current* only while
the latest successful extraction still has that excerpt at those offsets. Stale
evidence keeps the candidate's review decision but must not support CV claims,
match results or exports until it is re-linked to the current text.
"""

from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CandidateEvidence, DocumentExtraction


def current_texts(session: Session, document_ids: Iterable[UUID]) -> dict[UUID, str | None]:
    """The usable extracted text per document; None when the latest extraction did not succeed."""
    ids = set(document_ids)
    texts: dict[UUID, str | None] = dict.fromkeys(ids)
    if not ids:
        return texts
    for extraction in session.scalars(select(DocumentExtraction).where(DocumentExtraction.source_document_id.in_(ids))):
        if extraction.status == "succeeded" and extraction.extracted_text:
            texts[extraction.source_document_id] = extraction.extracted_text
    return texts


def is_current(evidence: CandidateEvidence, text: str | None) -> bool:
    if text is None:
        return False
    start, end = evidence.source_start, evidence.source_end
    if start is None or end is None:
        return evidence.source_excerpt is not None and evidence.source_excerpt in text
    if end > len(text):
        return False
    return evidence.source_excerpt is None or text[start:end] == evidence.source_excerpt


def mark_currency(session: Session, evidence: Sequence[CandidateEvidence]) -> list[CandidateEvidence]:
    """Attach ``source_current`` to each record (a transient attribute) and return them."""
    texts = current_texts(session, (item.source_document_id for item in evidence))
    for item in evidence:
        item.source_current = is_current(item, texts[item.source_document_id])
    return list(evidence)


def current_only(session: Session, evidence: Sequence[CandidateEvidence]) -> list[CandidateEvidence]:
    """Evidence whose source still matches; stale records are left out of any use."""
    return [item for item in mark_currency(session, evidence) if item.source_current]
