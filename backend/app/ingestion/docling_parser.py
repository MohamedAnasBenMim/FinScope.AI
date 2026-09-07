"""Optional Docling converter; native spreadsheet parsing retains exact formulas/cells."""

from pathlib import Path

from app.config import Settings
from app.errors import ParsingFailed
from app.ingestion.normalized import NormalizedBlock, NormalizedDocument, table_markdown


def convert_docling(path: Path, normalized: NormalizedDocument, config: Settings) -> NormalizedDocument:
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption
    except ImportError as exc:
        raise ParsingFailed(
            "Docling selected but not installed. Install backend/requirements-docling.txt."
        ) from exc
    options = PdfPipelineOptions(do_ocr=True, do_table_structure=True)
    options.ocr_options = TesseractCliOcrOptions(lang=config.OCR_LANGUAGES.split("+"))
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    result = converter.convert(
        str(path), max_num_pages=config.MAX_DOCUMENT_PAGES, max_file_size=config.MAX_FILE_SIZE
    )
    doc = result.document
    normalized.page_count = len(doc.pages) if normalized.extension == ".pdf" else None
    heading = None
    for item, _ in doc.iterate_items():
        label = str(item.label.value)
        prov = item.prov[0] if getattr(item, "prov", None) else None
        page = prov.page_no if prov and normalized.extension == ".pdf" else None
        bbox = [prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b] if prov else None
        if label == "table":
            frame = item.export_to_dataframe(doc=doc)
            rows = [list(map(str, frame.columns))] + frame.fillna("").astype(str).values.tolist()
            normalized.blocks.append(
                NormalizedBlock(
                    type="table",
                    text=table_markdown(rows),
                    page=page,
                    bbox=bbox,
                    section=heading,
                    heading=heading,
                    table_id=item.self_ref,
                    metadata={"rows": rows, "header_rows": 1},
                )
            )
        elif getattr(item, "text", "").strip():
            if label in ("section_header", "title"):
                heading = item.text
            normalized.blocks.append(
                NormalizedBlock(
                    type="heading" if label in ("section_header", "title") else "text",
                    text=item.text,
                    page=page,
                    bbox=bbox,
                    heading=heading,
                    section=heading,
                )
            )
    normalized.metadata.update(
        parser="docling", ocr_engine="tesseract", ocr_enabled=True, ocr_used=None, ocr_confidence=None
    )
    if not normalized.blocks:
        raise ParsingFailed("Docling returned no readable document blocks.")
    return normalized.assign_ids()
