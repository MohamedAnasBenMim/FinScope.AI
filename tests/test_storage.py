import asyncio
import io

import pytest
from app.config import Settings
from app.errors import CorruptedDocument, UnsupportedDocumentType, UploadTooLarge
from app.storage import LocalStorageProvider
from fastapi import UploadFile


def test_safe_storage_checksum_and_delete(tmp_path):
    storage = LocalStorageProvider(Settings(UPLOAD_DIR=tmp_path))
    file = asyncio.run(storage.save(UploadFile(filename="../../notes.txt", file=io.BytesIO(b"Hello world"))))
    assert file.filename == "notes.txt"
    assert file.key != file.filename
    assert file.checksum == "64ec88ca00b268e5ba1a35678a1b5316d212f4f366b2477232534a8aeca37f3c"
    assert storage.path(file.key).read_text() == "Hello world"
    with pytest.raises(ValueError):
        storage.delete("../outside.txt")
    storage.delete(file.key)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("name", "body", "error"),
    [
        ("x.txt", b"", CorruptedDocument),
        ("x.exe", b"hello", UnsupportedDocumentType),
        ("x.pdf", b"%PDF-1.7 corrupted", CorruptedDocument),
        ("x.txt", b"longer than ten bytes", UploadTooLarge),
    ],
)
def test_invalid_upload_cleanup(tmp_path, name, body, error):
    storage = LocalStorageProvider(
        Settings(UPLOAD_DIR=tmp_path, MAX_FILE_SIZE=10 if name == "x.txt" and body else 100)
    )
    with pytest.raises(error):
        asyncio.run(storage.save(UploadFile(filename=name, file=io.BytesIO(body))))
    assert not list(tmp_path.iterdir())
