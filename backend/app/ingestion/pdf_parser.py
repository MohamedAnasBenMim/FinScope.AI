from pathlib import Path
import pdfplumber
import pandas as pd
from app.ingestion.schemas import ExtractedTable, ParsedPage, ParsedDocument


class FinancialPDFParser:
    """Extracts text, structured tables, and page metadata from financial PDFs."""

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)

    @staticmethod
    def table_to_markdown(table_data: list[list[str]]) -> str:
        """Converts raw table matrix into a clean Markdown table format."""
        if not table_data or len(table_data) < 2:
            return ""

        # Remove None values and strip whitespace
        cleaned_data = [
            [cell.strip() if cell else "" for cell in row]
            for row in table_data
        ]

        header = cleaned_data[0]
        rows = cleaned_data[1:]

        # Create Pandas DataFrame to format cleanly as markdown
        df = pd.DataFrame(rows, columns=header)
        return df.to_markdown(index=False)

    def parse(self) -> ParsedDocument:
        """Parses the PDF document page by page."""
        pages: list[ParsedPage] = []

        with pdfplumber.open(self.pdf_path) as pdf:
            total_pages = len(pdf.pages)

            for idx, page in enumerate(pdf.pages):
                page_num = idx + 1
                page_text = page.extract_text() or ""
                extracted_tables: list[ExtractedTable] = []
                markdown_sections: list[str] = [page_text]

                # Extract tables using pdfplumber table finder
                tables = page.extract_tables()
                for table_idx, raw_table in enumerate(tables):
                    md_table = self.table_to_markdown(raw_table)
                    if md_table:
                        headers = [str(h) for h in raw_table[0] if h]
                        table_obj = ExtractedTable(
                            page_number=page_num,
                            table_index=table_idx + 1,
                            markdown_content=md_table,
                            headers=headers,
                            num_rows=len(raw_table),
                            num_cols=len(raw_table[0]) if raw_table else 0
                        )
                        extracted_tables.append(table_obj)
                        markdown_sections.append(f"\n\n### [Table {table_idx + 1} - Page {page_num}]\n{md_table}\n")

                combined_md = "\n".join(markdown_sections)
                pages.append(ParsedPage(
                    page_number=page_num,
                    text_content=page_text,
                    tables=extracted_tables,
                    combined_markdown=combined_md
                ))

        return ParsedDocument(
            filename=self.pdf_path.name,
            total_pages=total_pages,
            metadata={"file_size_bytes": str(self.pdf_path.stat().st_size)},
            pages=pages
        )
