import sys
from pathlib import Path
from app.ingestion.pdf_parser import FinancialPDFParser

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_parser.py <path_to_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    parser = FinancialPDFParser(pdf_path)
    doc = parser.parse()

    print(f"✅ Successfully parsed {doc.filename}")
    print(f"Total Pages: {doc.total_pages}")
    for page in doc.pages:
        print(f"Page {page.page_number}: {len(page.tables)} tables extracted")
