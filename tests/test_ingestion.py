import json
from pathlib import Path

import pytest
from app.config import Settings
from app.ingestion.classifier import DocumentClassifier
from app.ingestion.extraction import StructuredExtractor, parse_number
from app.ingestion.normalized import NormalizedBlock, NormalizedDocument
from app.ingestion.parsers import DocumentParser
from app.ingestion.validation import validate_file

from scripts.generate_test_documents import FIXTURES, generate


@pytest.fixture(scope="session", autouse=True)
def corpus():
    generate()
    return FIXTURES / "documents"


def parse(path, config=None):
    config = config or Settings()
    mime, extension = validate_file(path, path.name, config)
    return DocumentParser(config).parse(path, "test-document", path.name, mime, extension)


@pytest.mark.parametrize(
    "filename",
    [
        "invoice_fr_01.pdf",
        "invoice_en_03.docx",
        "invoice_en_05.xls",
        "devis_fr_02.xlsx",
        "quote_en_04.csv",
        "quote_fr_05.txt",
        "bilan_fr_01.pdf",
        "other_readme.md",
        "other_page.html",
        "other_slides.pptx",
    ],
)
def test_formats(corpus, filename):
    doc = parse(corpus / filename)
    assert doc.blocks and all(block.block_id for block in doc.blocks)
    if Path(filename).suffix not in (".pdf",):
        assert doc.page_count is None
        assert all(b.page is None for b in doc.blocks)


def test_native_classification_extraction(corpus):
    truth = json.loads((FIXTURES / "ground_truth.json").read_text())
    for filename, expected in truth.items():
        if filename.endswith((".png", ".jpg")):
            continue
        doc = parse(corpus / filename)
        classification = DocumentClassifier().classify(doc)
        assert classification.document_type == expected["document_type"], (filename, classification)
        doc.document_type = classification.document_type
        extracted = StructuredExtractor().extract(doc)
        for field in (
            "total",
            "net_income",
            "revenue",
            "invoice_number",
            "quote_number",
            "currency",
            "validity",
        ):
            if field in expected:
                assert extracted[field] is not None, (filename, field, extracted)
                assert extracted[field]["value"] == expected[field], (filename, field, extracted[field])
                assert extracted[field]["source"]["document_id"] == doc.document_id


def test_uncertain_classification():
    doc = NormalizedDocument(
        document_id="x",
        filename="INVOICE.pdf",
        mime_type="text/plain",
        extension=".txt",
        blocks=[NormalizedBlock(text="We discussed an invoice during the garden meeting.")],
    )
    assert DocumentClassifier().classify(doc).document_type == "other"
    doc.blocks = [NormalizedBlock(text="FACTURE: FAC-123\nTVA: 20\nTotal TTC: 120")]
    assert DocumentClassifier(threshold=0.99).classify(doc).document_type == "other"


def test_tables_and_formula_provenance(corpus):
    doc = parse(corpus / "bilan_fr_01.pdf")
    assert any(b.type == "table" and b.page == 1 and b.metadata["rows"] for b in doc.blocks)
    formula_doc = parse(corpus / "formulas.xlsx")
    assert formula_doc.blocks[0].metadata["formulas"] == {"C2": "=B2*2"}
    assert "cached value unavailable" in formula_doc.blocks[0].text
    assert formula_doc.blocks[0].cell_range == "A1:C2"


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1 428,00 EUR", 1428),
        ("1,428.00", 1428),
        ("(450,50)", -450.5),
        ("1.428,25", 1428.25),
        ("unknown", None),
    ],
)
def test_number_locales(text, value):
    assert parse_number(text) == value


def test_arithmetic_warnings_and_missing_values(corpus):
    doc = parse(corpus / "invoice_fr_01.pdf")
    doc.document_type = "invoice"
    for block in doc.blocks:
        block.text = block.text.replace("Montant TTC: 1428.00", "Montant TTC: 999.00")
    extracted = StructuredExtractor().extract(doc)
    assert extracted["total"]["value"] == 999
    assert extracted["warnings"]
    assert extracted["supplier"]["address"] is None


@pytest.mark.integration
@pytest.mark.parametrize(
    "filename",
    [
        "scanned_invoice.pdf",
        "invoice_scan_fr_02.png",
        "invoice_photo_en_04.jpg",
        "scanned_invoice.webp",
        "scanned_invoice.tiff",
    ],
)
def test_real_ocr(corpus, filename):
    doc = parse(corpus / filename)
    assert doc.metadata["ocr_used"]
    assert doc.metadata["ocr_engine"] == "tesseract"
    assert doc.metadata["ocr_confidence"] > 0.3
    assert DocumentClassifier().classify(doc).document_type == "invoice"
    assert any(b.bbox for b in doc.blocks)
