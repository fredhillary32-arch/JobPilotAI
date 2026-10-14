from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import BinaryIO
from uuid import UUID, uuid4

MAX_DOCUMENT_SIZE_BYTES = 10 * 1024 * 1024
CHUNK_SIZE_BYTES = 64 * 1024
ALLOWED_DOCUMENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


class DocumentValidationError(ValueError):
    pass


class DocumentTooLargeError(DocumentValidationError):
    pass


class EmptyDocumentError(DocumentValidationError):
    pass


class DocumentStorageError(OSError):
    pass


@dataclass(frozen=True)
class StoredDocument:
    storage_key: str
    size_bytes: int
    sha256: str


class DocumentStorage:
    def store(
        self,
        source: BinaryIO,
        *,
        suffix: str,
    ) -> StoredDocument:
        raise NotImplementedError

    def resolve(self, storage_key: str) -> Path:
        raise NotImplementedError

    def remove(self, storage_key: str) -> None:
        raise NotImplementedError


class LocalDocumentStorage(DocumentStorage):
    def __init__(self, storage_root: Path) -> None:
        self.storage_root = storage_root

    def store(
        self,
        source: BinaryIO,
        *,
        suffix: str,
    ) -> StoredDocument:
        self.storage_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        document_id = uuid4().hex
        storage_key = f"{document_id}{suffix}"
        target = self.resolve(storage_key)
        temporary = self.resolve(f".{document_id}.tmp")
        digest = sha256()
        size_bytes = 0

        try:
            with temporary.open("xb") as destination:
                while chunk := source.read(CHUNK_SIZE_BYTES):
                    size_bytes += len(chunk)
                    if size_bytes > MAX_DOCUMENT_SIZE_BYTES:
                        raise DocumentTooLargeError("Document exceeds the 10 MB limit")
                    digest.update(chunk)
                    destination.write(chunk)
            if size_bytes == 0:
                raise EmptyDocumentError("Document must not be empty")
            temporary.replace(target)
        except (DocumentValidationError, OSError):
            temporary.unlink(missing_ok=True)
            raise

        return StoredDocument(storage_key, size_bytes, digest.hexdigest())

    def resolve(self, storage_key: str) -> Path:
        root = self.storage_root.resolve()
        path = (root / storage_key).resolve()
        if path.parent != root:
            raise DocumentStorageError("Invalid document storage key")
        return path

    def remove(self, storage_key: str) -> None:
        path = self.resolve(storage_key)
        path.unlink(missing_ok=True)


def validate_document(
    source: BinaryIO,
    *,
    filename: str,
    declared_media_type: str,
) -> tuple[str, str]:
    suffix = Path(filename).suffix.lower()
    expected_media_type = ALLOWED_DOCUMENT_TYPES.get(suffix)
    if expected_media_type is None:
        raise DocumentValidationError("Only PDF, DOCX, and TXT documents are accepted")
    if declared_media_type.lower() != expected_media_type:
        raise DocumentValidationError("File extension and content type do not match")

    source.seek(0)
    header = source.read(4096)
    source.seek(0)
    if not header:
        raise EmptyDocumentError("Document must not be empty")
    if suffix == ".pdf" and b"%PDF-" not in header[:1024]:
        raise DocumentValidationError("File does not contain a valid PDF header")
    if suffix == ".docx":
        import zipfile

        try:
            with zipfile.ZipFile(source) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise DocumentValidationError("File is not a valid DOCX document")
        except zipfile.BadZipFile as exc:
            raise DocumentValidationError("File is not a valid DOCX document") from exc
        finally:
            source.seek(0)
    if suffix == ".txt":
        try:
            decoded_header = header.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentValidationError("Text documents must use UTF-8 encoding") from exc
        if "\x00" in decoded_header:
            raise DocumentValidationError("Text documents must not contain binary data")

    return suffix, expected_media_type


def get_document_storage() -> DocumentStorage:
    from app.settings import get_settings

    return LocalDocumentStorage(get_settings().resolved_document_storage_path)
