import importlib.metadata
import unicodedata
import zipfile
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Literal
from xml.etree.ElementTree import ParseError

import pymupdf
from docx import Document as DocxDocument
from docx.document import Document as DocxDocumentObject
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.exceptions import InvalidXmlError
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from app.models import CandidateDocument
from app.services.documents import (
    MAX_DOCUMENT_SIZE_BYTES,
    DocumentStorage,
    DocumentStorageError,
)

MAX_PDF_PAGES = 1000
MAX_EXTRACTED_CHARACTERS = 500_000
MAX_DOCX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_DOCX_ARCHIVE_ITEMS = 2000
MAX_DOCX_COMPRESSION_RATIO = 200

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


@dataclass(frozen=True)
class ExtractionOutcome:
    status: ExtractionStatus
    extracted_text: str | None
    character_count: int
    extractor_version: str
    error_category: ExtractionErrorCategory | None


class ExtractionFailure(Exception):
    def __init__(self, category: ExtractionErrorCategory) -> None:
        super().__init__(category)
        self.category = category


def _parser_version(media_type: str) -> str:
    if media_type == "application/pdf":
        package = "PyMuPDF"
        version = importlib.metadata.version(package)
    elif media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        package = "python-docx"
        version = importlib.metadata.version(package)
    else:
        package, version = "stdlib", "stdlib"
    return f"{package}/{version}"


def normalize_extracted_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    normalized: list[str] = []
    for character in value:
        if character in "\n\t":
            normalized.append(character)
        elif unicodedata.category(character) not in {"Cc", "Cs"}:
            normalized.append(character)
    lines = [line.rstrip() for line in "".join(normalized).split("\n")]
    result = "\n".join(lines).strip()
    if len(result) > MAX_EXTRACTED_CHARACTERS:
        raise ExtractionFailure("resource_limit")
    return result


def _has_usable_text(value: str) -> bool:
    return any(character.isalnum() for character in value)


def _extract_pdf(data: bytes) -> str:
    try:
        with pymupdf.open(stream=data, filetype="pdf") as document:
            if document.needs_pass:
                raise ExtractionFailure("encrypted_document")
            if document.page_count > MAX_PDF_PAGES:
                raise ExtractionFailure("resource_limit")
            pages: list[str] = []
            character_count = 0
            for page in document:
                page_text = page.get_text("text", sort=True)
                character_count += len(page_text)
                if character_count > MAX_EXTRACTED_CHARACTERS:
                    raise ExtractionFailure("resource_limit")
                if page_text.strip():
                    pages.append(page_text)
            return "\n\n".join(pages)
    except ExtractionFailure:
        raise
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise ExtractionFailure("invalid_document") from exc


def _check_docx_resource_limits(data: bytes) -> None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ARCHIVE_ITEMS:
                raise ExtractionFailure("resource_limit")
            total_uncompressed = 0
            for entry in entries:
                total_uncompressed += entry.file_size
                if total_uncompressed > MAX_DOCX_UNCOMPRESSED_BYTES:
                    raise ExtractionFailure("resource_limit")
                if entry.file_size and entry.compress_size == 0:
                    raise ExtractionFailure("resource_limit")
                if entry.compress_size and entry.file_size / entry.compress_size > MAX_DOCX_COMPRESSION_RATIO:
                    raise ExtractionFailure("resource_limit")
    except ExtractionFailure:
        raise
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ExtractionFailure("invalid_document") from exc


def _extract_docx(data: bytes) -> str:
    _check_docx_resource_limits(data)
    try:
        document: DocxDocumentObject = DocxDocument(BytesIO(data))
        blocks: list[str] = []
        character_count = 0
        for child in document.element.body.iterchildren():
            if isinstance(child, CT_P):
                paragraph = Paragraph(child, document)
                if paragraph.text.strip():
                    blocks.append(paragraph.text)
                    character_count += len(paragraph.text)
            elif isinstance(child, CT_Tbl):
                table = Table(child, document)
                for row in table.rows:
                    cells = [" ".join(cell.text.splitlines()).strip() for cell in row.cells]
                    row_text = "\t".join(cell for cell in cells if cell)
                    if row_text:
                        blocks.append(row_text)
                        character_count += len(row_text)
            if character_count + max(0, len(blocks) - 1) * 2 > MAX_EXTRACTED_CHARACTERS:
                raise ExtractionFailure("resource_limit")
        return "\n\n".join(blocks)
    except ExtractionFailure:
        raise
    except (
        ValueError,
        OSError,
        KeyError,
        zipfile.BadZipFile,
        ParseError,
        PackageNotFoundError,
        InvalidXmlError,
    ) as exc:
        raise ExtractionFailure("invalid_document") from exc


def extract_document_text(
    source_document: CandidateDocument,
    storage: DocumentStorage,
) -> ExtractionOutcome:
    media_type = source_document.media_type
    version = _parser_version(media_type)
    try:
        path: Path = storage.resolve(source_document.storage_key)
        if not path.is_file():
            raise ExtractionFailure("missing_file")
        if path.stat().st_size > min(
            source_document.size_bytes,
            MAX_DOCUMENT_SIZE_BYTES,
        ):
            raise ExtractionFailure("resource_limit")
        data = path.read_bytes()
    except ExtractionFailure:
        raise
    except DocumentStorageError as exc:
        raise ExtractionFailure("missing_file") from exc
    except OSError as exc:
        raise ExtractionFailure("missing_file") from exc

    if not data:
        raise ExtractionFailure("invalid_document")
    if len(data) > min(source_document.size_bytes, MAX_DOCUMENT_SIZE_BYTES):
        raise ExtractionFailure("resource_limit")
    if sha256(data).hexdigest() != source_document.sha256:
        raise ExtractionFailure("invalid_document")

    if media_type == "application/pdf" and path.suffix.lower() == ".pdf":
        raw_text = _extract_pdf(data)
    elif (
        media_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        and path.suffix.lower() == ".docx"
    ):
        raw_text = _extract_docx(data)
    elif media_type == "text/plain" and path.suffix.lower() == ".txt":
        try:
            raw_text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ExtractionFailure("decoding_error") from exc
    else:
        raise ExtractionFailure("unsupported_content")

    normalized = normalize_extracted_text(raw_text)
    if not _has_usable_text(normalized):
        return ExtractionOutcome(
            status="no_text",
            extracted_text=None,
            character_count=0,
            extractor_version=version,
            error_category=None,
        )
    return ExtractionOutcome(
        status="succeeded",
        extracted_text=normalized,
        character_count=len(normalized),
        extractor_version=version,
        error_category=None,
    )
