"""Content validation before a document is admitted to the durable queue."""

import csv
import io
import re
import zipfile
from pathlib import Path

import magic
import pypdfium2
from app.config import Settings
from app.errors import CorruptedDocument, UnsupportedDocumentType
from PIL import Image

MIMES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}
OOXML_ROOTS = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip().strip(".")
    if not name or len(name) > 240:
        raise CorruptedDocument("Filename is empty or exceeds 240 characters.")
    return name


def decode_text(data: bytes) -> str:
    try:
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CorruptedDocument("Text documents must use UTF-8 or BOM-marked UTF-16.") from exc
    if any(ord(c) < 32 and c not in "\n\r\t\f" for c in text):
        raise CorruptedDocument("Binary/control bytes detected in a text document.")
    if not text.strip():
        raise CorruptedDocument("The document is empty.")
    return text


def validate_file(path: Path, filename: str, config: Settings) -> tuple[str, str]:
    extension = Path(filename).suffix.lower()
    if extension not in MIMES:
        raise UnsupportedDocumentType(
            f"Unsupported extension {extension or '(none)'}. Supported: {', '.join(MIMES)}"
        )
    if path.stat().st_size == 0:
        raise CorruptedDocument("The uploaded file is empty.")
    with path.open("rb") as stream:
        signature = stream.read(8192)
    detected = magic.from_buffer(signature, mime=True)
    expected = MIMES[extension]
    try:
        if extension == ".pdf":
            if not signature.startswith(b"%PDF-"):
                raise CorruptedDocument("Invalid PDF signature; the content is not a PDF.")
            with pypdfium2.PdfDocument(str(path)) as pdf:
                if not 0 < len(pdf) <= config.MAX_DOCUMENT_PAGES:
                    raise CorruptedDocument("PDF is empty or exceeds MAX_DOCUMENT_PAGES.")
        elif expected.startswith("image/"):
            with Image.open(path) as img:
                if Image.MIME.get(img.format) != expected:
                    raise CorruptedDocument("Image content does not match its extension.")
                if img.width * img.height > config.MAX_IMAGE_PIXELS:
                    raise CorruptedDocument("Image exceeds MAX_IMAGE_PIXELS.")
                if getattr(img, "n_frames", 1) > config.MAX_DOCUMENT_PAGES:
                    raise CorruptedDocument("Image exceeds MAX_DOCUMENT_PAGES.")
                img.verify()
        elif extension in OOXML_ROOTS:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(e.file_size for e in entries) > config.MAX_ARCHIVE_BYTES:
                    raise CorruptedDocument("Office archive exceeds decompression limits.")
                names = archive.namelist()
                if OOXML_ROOTS[extension] not in names or "[Content_Types].xml" not in names:
                    raise CorruptedDocument("Office archive does not match its extension.")
                if any("vbaproject" in n.lower() or "activex" in n.lower() for n in names):
                    raise UnsupportedDocumentType("Macro-enabled or ActiveX documents are not accepted.")
                if any(e.flag_bits & 1 for e in entries):
                    raise CorruptedDocument("Encrypted Office documents are not supported.")
                if archive.testzip() is not None:
                    raise CorruptedDocument("Office archive failed its integrity check.")
        elif extension == ".xls":
            if not signature.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
                raise CorruptedDocument("Invalid legacy Excel signature.")
            import xlrd

            with xlrd.open_workbook(str(path), on_demand=True) as workbook:
                if not workbook.nsheets:
                    raise CorruptedDocument("Excel workbook has no sheets.")
        else:
            # CSV/Markdown often sniff as text/plain, OOXML as application/zip.
            if not (
                detected.startswith("text/") or detected in ("application/csv", "application/octet-stream")
            ):
                raise CorruptedDocument(f"Expected text, detected {detected}.")
            text = decode_text(path.read_bytes())
            if extension in (".html", ".htm") and not re.search(r"<[a-zA-Z][^>]*>", text):
                raise CorruptedDocument("No HTML elements detected.")
            if extension == ".csv":
                dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
                list(csv.reader(io.StringIO(text), dialect))
        return expected, extension
    except (CorruptedDocument, UnsupportedDocumentType):
        raise
    except (Exception,) as exc:
        # File libraries use different exception classes for malformed containers.
        raise CorruptedDocument(
            f"Cannot read {extension} document: {type(exc).__name__}. It may be corrupted or encrypted."
        ) from exc
