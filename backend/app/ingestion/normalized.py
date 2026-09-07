from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, Field


class Classification(BaseModel):
    document_type: str = "other"
    confidence: float = Field(0, ge=0, le=1)
    reason: str = "No confident financial classification."
    signals: list[str] = Field(default_factory=list)


class NormalizedBlock(BaseModel):
    block_id: str = ""
    type: Literal["text", "heading", "list", "table", "spreadsheet", "OCR"] = "text"
    text: str
    page: int | None = None
    section: str | None = None
    heading: str | None = None
    table_id: str | None = None
    sheet_name: str | None = None
    slide_number: int | None = None
    cell_range: str | None = None
    bbox: list[float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NormalizedDocument(BaseModel):
    document_id: str
    filename: str
    mime_type: str
    extension: str
    page_count: int | None = None
    document_type: str = "other"
    classification_confidence: float = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list[NormalizedBlock] = Field(default_factory=list)

    def assign_ids(self) -> "NormalizedDocument":
        for index, block in enumerate(self.blocks):
            block.block_id = str(uuid5(NAMESPACE_URL, f"{self.document_id}/block/{index}/{block.text}"))
        return self


def table_markdown(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    width = max(map(len, rows))
    cleaned = [
        [str(cell if cell is not None else "").replace("|", "\\|").replace("\n", " ") for cell in row]
        + [""] * (width - len(row))
        for row in rows
    ]
    lines = ["| " + " | ".join(row) + " |" for row in cleaned]
    lines.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(lines)
