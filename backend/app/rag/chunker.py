from pydantic import BaseModel, Field
from app.ingestion.schemas import ParsedDocument


class DocumentChunk(BaseModel):
    """Represents a single chunk ready for vector embedding and retrieval."""

    chunk_id: str
    filename: str
    page_number: int
    content: str
    is_table: bool
    metadata: dict[str, str] = Field(default_factory=dict)


class FinancialChunker:
    """Splits narrative text into ~500 token chunks while preserving tables as intact units."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk_document(self, doc: ParsedDocument) -> list[DocumentChunk]:
        chunks: list[DocumentChunk] = []

        for page in doc.pages:
            # 1. Store each table as an intact, standalone chunk
            for table in page.tables:
                chunk_id = f"{doc.filename}_p{page.page_number}_tbl{table.table_index}"
                chunks.append(DocumentChunk(
                    chunk_id=chunk_id,
                    filename=doc.filename,
                    page_number=page.page_number,
                    content=table.markdown_content,
                    is_table=True,
                    metadata={
                        "headers": ", ".join(table.headers),
                        "num_rows": str(table.num_rows),
                        "num_cols": str(table.num_cols)
                    }
                ))

            # 2. Chunk narrative text with overlap
            words = page.text_content.split()
            if words:
                start = 0
                seq = 1
                while start < len(words):
                    end = start + self.chunk_size
                    chunk_words = words[start:end]
                    chunk_text = " ".join(chunk_words)

                    chunk_id = f"{doc.filename}_p{page.page_number}_txt{seq}"
                    chunks.append(DocumentChunk(
                        chunk_id=chunk_id,
                        filename=doc.filename,
                        page_number=page.page_number,
                        content=chunk_text,
                        is_table=False,
                        metadata={"word_count": str(len(chunk_words))}
                    ))

                    start += (self.chunk_size - self.chunk_overlap)
                    seq += 1

        return chunks
