import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.errors import UploadTooLarge
from app.ingestion.validation import safe_filename, validate_file
from fastapi import UploadFile


@dataclass
class StoredFile:
    filename: str
    key: str
    checksum: str
    size: int
    mime_type: str
    extension: str


class StorageProvider(ABC):
    @abstractmethod
    async def save(self, upload: UploadFile) -> StoredFile: ...

    @abstractmethod
    def path(self, key: str) -> Path: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalStorageProvider(StorageProvider):
    def __init__(self, config: Settings):
        self.config = config
        self.root = config.UPLOAD_DIR.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if target.parent != self.root or Path(key).name != key:
            raise ValueError("Invalid storage key.")
        return target

    async def save(self, upload: UploadFile) -> StoredFile:
        from starlette.concurrency import run_in_threadpool

        filename = safe_filename(upload.filename or "")
        key = f"{uuid4()}{Path(filename).suffix.lower()}"
        path = self.path(key)
        size = 0
        checksum = hashlib.sha256()
        try:
            with path.open("xb") as stream:
                while data := await upload.read(1024 * 1024):
                    size += len(data)
                    if size > self.config.MAX_FILE_SIZE:
                        raise UploadTooLarge(
                            f"File exceeds MAX_FILE_SIZE ({self.config.MAX_FILE_SIZE} bytes)."
                        )
                    checksum.update(data)
                    await run_in_threadpool(stream.write, data)
            mime, extension = await run_in_threadpool(validate_file, path, filename, self.config)
            return StoredFile(filename, key, checksum.hexdigest(), size, mime, extension)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)
