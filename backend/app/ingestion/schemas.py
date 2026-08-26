from pydantic import BaseModel, Field


class ExtractedTable(BaseModel):
    """Represents a single table extracted from a financial document page."""

    page_number: int
    table_index: int
    markdown_content: str
    headers: list[str] = Field(default_factory=list)
    num_rows: int
    num_cols: int


class ParsedPage(BaseModel):
    """Represents a parsed page containing both narrative text and structured tables."""

    page_number: int
    text_content: str
    tables: list[ExtractedTable] = Field(default_factory=list)
    combined_markdown: str  # Narrative text + inline Markdown tables


class ParsedDocument(BaseModel):
    """Represents the complete parsed financial document."""

    filename: str
    total_pages: int
    metadata: dict[str, str] = Field(default_factory=dict)
    pages: list[ParsedPage] = Field(default_factory=list)
