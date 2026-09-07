from uuid import NAMESPACE_URL, uuid5

from app.config import Settings
from app.ingestion.normalized import NormalizedBlock, NormalizedDocument, table_markdown
from openpyxl.utils import get_column_letter
from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    chunk_id: str
    content: str
    metadata: dict = Field(default_factory=dict)


class FinancialChunker:
    """Pack paragraphs within one location; split tables by rows with repeated headers."""

    def __init__(self, config: Settings | None = None):
        self.config = config or Settings()

    def chunk_document(self, doc: NormalizedDocument) -> list[DocumentChunk]:
        chunks = []
        pending = []
        pending_words = 0
        location = None

        def emit(text: str, block: NormalizedBlock, extra: dict | None = None):
            if not text.strip():
                return
            index = len(chunks)
            metadata = {
                "document_id": doc.document_id,
                "filename": doc.filename,
                "document_type": doc.document_type,
                "page": block.page,
                "page_start": block.page,
                "page_end": block.page,
                "section": block.section,
                "heading": block.heading,
                "table_id": block.table_id,
                "sheet_name": block.sheet_name,
                "cell_range": block.cell_range,
                "slide_number": block.slide_number,
                "chunk_index": index,
                "content_type": block.type if block.type in ("table", "spreadsheet", "OCR") else "text",
                "block_ids": [block.block_id],
                "bbox": block.bbox,
                **(extra or {}),
            }
            chunk_id = str(uuid5(NAMESPACE_URL, f"{doc.document_id}/chunk/{index}/{text}"))
            chunks.append(DocumentChunk(chunk_id=chunk_id, content=text, metadata=metadata))

        def flush():
            if pending:
                text = "\n".join(b.text for b in pending)
                first, last = pending[0], pending[-1]
                if first.heading and not text.startswith(first.heading):
                    text = first.heading + "\n" + text
                emit(
                    text,
                    first,
                    {
                        "block_ids": [b.block_id for b in pending],
                        "line_start": first.metadata.get("line_start"),
                        "line_end": last.metadata.get("line_end"),
                    },
                )
                pending.clear()

        for block in doc.blocks:
            here = (block.page, block.section, block.sheet_name, block.slide_number, block.type == "OCR")
            rows = block.metadata.get("rows")
            if rows:
                flush()
                pending_words = 0
                header_count = block.metadata.get("header_rows", 1)
                headers = rows[:header_count]
                data_rows = rows[header_count:]
                if not data_rows:
                    emit(block.text, block)
                    continue
                start = 0
                while start < len(data_rows):
                    end = start
                    words = sum(len(str(c).split()) for row in headers for c in row)
                    while end < len(data_rows) and end - start < self.config.TABLE_CHUNK_ROWS:
                        row_words = sum(len(str(c).split()) for c in data_rows[end])
                        if end > start and words + row_words > self.config.CHUNK_WORDS:
                            break
                        words += row_words
                        end += 1
                    selected = headers + data_rows[start:end]
                    extra = {
                        "rows": selected,
                        "row_start": block.metadata.get("row_start", 1) + header_count + start,
                        "row_end": block.metadata.get("row_start", 1) + header_count + end - 1,
                    }
                    if block.sheet_name:
                        first_row = block.metadata.get("row_start", 1) + header_count + start
                        last_row = block.metadata.get("row_start", 1) + header_count + end - 1
                        # Include header location separately when a table spans chunks.
                        extra["cell_range"] = (
                            f"A{first_row}:{get_column_letter(max(map(len, selected)))}{last_row}"
                        )
                        extra["header_cell_range"] = (
                            f"A{block.metadata.get('row_start', 1)}:{get_column_letter(max(map(len, headers)))}{block.metadata.get('row_start', 1) + header_count - 1}"
                            if headers
                            else None
                        )
                    content = table_markdown(selected)
                    if block.heading or block.sheet_name:
                        content = (block.heading or block.sheet_name) + "\n" + content
                    emit(content, block, extra)
                    start = end
                continue
            block_words = len(block.text.split())
            if (
                here != location
                or pending_words + block_words > self.config.CHUNK_WORDS
                or block.type == "heading"
            ):
                flush()
                pending_words = 0
            location = here
            if block_words > self.config.CHUNK_WORDS:
                # An oversized paragraph is the fallback, not the primary strategy.
                words = block.text.split()
                for start in range(0, len(words), self.config.CHUNK_WORDS):
                    text = " ".join(words[start : start + self.config.CHUNK_WORDS])
                    emit((block.heading + "\n" if block.heading else "") + text, block)
            else:
                pending.append(block)
                pending_words += block_words
        flush()
        return chunks
