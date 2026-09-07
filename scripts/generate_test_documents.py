"""Generate a deterministic fictional bilingual corpus; no external data is used."""

import csv
import json
import zipfile
from datetime import datetime
from pathlib import Path

from docx import Document
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def canonicalize_office(path: Path):
    """OOXML ZIP timestamps must not change duplicate checks between corpus generations."""
    with zipfile.ZipFile(path) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            entry = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, entries[name])


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures"


def render_image(lines: list[str], rows: list[list[str]]) -> Image.Image:
    image = Image.new("RGB", (1800, max(1400, (len(lines) + len(rows) + 3) * 65)), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 34) if font_path.exists() else ImageFont.load_default(size=34)
    for i, line in enumerate(lines + [""] + ["    ".join(row) for row in rows]):
        draw.text((70, 60 + i * 62), line, fill="black", font=font)
    return image


def write_document(path: Path, lines: list[str], rows: list[list[str]]):
    suffix = path.suffix
    if suffix == ".pdf":
        styles = getSampleStyleSheet()
        content = []
        for i, line in enumerate(lines):
            content.append(Paragraph(line, styles["Heading1" if i == 0 else "Normal"]))
            content.append(Spacer(1, 8))
        if rows:
            table = Table(rows)
            table.setStyle(
                TableStyle(
                    [
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ]
                )
            )
            content.append(table)
        SimpleDocTemplate(str(path), pagesize=A4, invariant=1).build(content)
    elif suffix in (".png", ".jpg", ".jpeg", ".webp", ".tiff"):
        render_image(lines, rows).save(path)
    elif suffix == ".docx":
        doc = Document()
        doc.add_heading(lines[0], 0)
        for line in lines[1:]:
            doc.add_paragraph(line)
        if rows:
            doc.add_heading("Pricing", 1)
            table = doc.add_table(rows=0, cols=len(rows[0]))
            for row in rows:
                for cell, value in zip(table.add_row().cells, row):
                    cell.text = str(value)
        doc.core_properties.created = doc.core_properties.modified = datetime(2026, 1, 1)
        doc.save(path)
        canonicalize_office(path)
    elif suffix in (".xlsx", ".xls"):
        all_rows = [[line] for line in lines] + [[]] + rows
        if suffix == ".xlsx":
            workbook = Workbook()
            workbook.active.title = (
                "Balance Sheet" if "balance" in path.name or "bilan" in path.name else "Pricing"
            )
            for row in all_rows:
                workbook.active.append(row)
            workbook.properties.created = workbook.properties.modified = datetime(2026, 1, 1)
            workbook.save(path)
            canonicalize_office(path)
        else:
            import xlwt

            workbook = xlwt.Workbook()
            sheet = workbook.add_sheet("Pricing")
            for r, row in enumerate(all_rows):
                for c, value in enumerate(row):
                    sheet.write(r, c, value)
            workbook.save(str(path))
    elif suffix == ".csv":
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            for line in lines:
                writer.writerow([line, ""])
            writer.writerow(["", ""])
            writer.writerows(rows)
    elif suffix == ".md":
        from app.ingestion.normalized import table_markdown

        path.write_text("\n".join(lines) + "\n\n" + table_markdown(rows), encoding="utf-8")
    elif suffix == ".html":
        from html import escape

        path.write_text(
            "<html><body>" + "".join(f"<p>{escape(line)}</p>" for line in lines) + "</body></html>",
            encoding="utf-8",
        )
    else:
        path.write_text("\n".join(lines + [""] + [" | ".join(r) for r in rows]), encoding="utf-8")


def generate(destination: Path = FIXTURES) -> dict:
    documents = destination / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    truth = {}
    invoice_names = [
        "invoice_fr_01.pdf",
        "invoice_scan_fr_02.png",
        "invoice_en_03.docx",
        "invoice_photo_en_04.jpg",
        "invoice_en_05.xls",
    ]
    quote_names = [
        "devis_fr_01.pdf",
        "devis_fr_02.xlsx",
        "quote_en_03.docx",
        "quote_en_04.csv",
        "quote_fr_05.txt",
    ]
    bilan_names = [
        "bilan_fr_01.pdf",
        "balance_sheet_en_02.xlsx",
        "financial_report_fr_03.pdf",
        "financial_statement_en_04.csv",
        "bilan_fr_05.docx",
    ]
    for i, filename in enumerate(invoice_names, 1):
        french = i <= 2
        reference = f"FAC-2026-{i:03}" if french else f"INV-2026-{i:03}"
        subtotal = 1190 + (i - 1) * 100
        tax = subtotal * 0.2
        total = subtotal + tax
        lines = [
            f"FACTURE : {reference}" if french else f"INVOICE: {reference}",
            "Fournisseur: Atelier Aurore SARL" if french else "Supplier: Northwind Fictional Ltd",
            "Client: ABC Formation" if french else "Customer: ABC Training",
            "Date: 2026-02-01",
            "Echeance: 2026-03-01" if french else "Due date: 2026-03-01",
            "Currency: EUR",
            "Tax ID: FR12345678901",
            f"Total HT: {subtotal:.2f}" if french else f"Subtotal: {subtotal:.2f}",
            f"Montant TVA: {tax:.2f}" if french else f"Tax amount: {tax:.2f}",
            f"Montant TTC: {total:.2f}" if french else f"Grand total: {total:.2f}",
            "Payment terms: 30 days",
            "IBAN: FR7612345678901234567890123",
        ]
        rows = [
            ["Description", "Quantity", "Unit price", "VAT", "Amount"],
            ["Consulting", "2", f"{subtotal / 2:.2f}", "20%", f"{subtotal:.2f}"],
        ]
        write_document(documents / filename, lines, rows)
        truth[filename] = {
            "document_type": "invoice",
            "invoice_number": reference,
            "total": total,
            "currency": "EUR",
            "page": 1 if filename.endswith(".pdf") else None,
        }
    for i, filename in enumerate(quote_names, 1):
        reference = f"DEV-2026-{i:03}"
        subtotal = 1000 + (i - 1) * 100
        lines = [
            f"DEVIS: {reference}",
            "Fournisseur: Atelier Aurore SARL",
            "Client: ABC Formation",
            "Date: 2026-01-01",
            "Validite: 30 jours",
            "Valid until: 2026-01-31",
            "Currency: EUR",
            f"Total HT: {subtotal:.2f}",
            f"Montant TVA: {subtotal * 0.2:.2f}",
            f"Montant TTC: {subtotal * 1.2:.2f}",
            "Bon pour accord",
            "Payment terms: 30 days",
        ]
        if i in (3, 4):
            lines[0] = f"QUOTATION: {reference}"
            lines[1:3] = ["Supplier: Atelier Aurore SARL", "Customer: ABC Training"]
        rows = [
            ["Description", "Quantity", "Unit price", "VAT", "Amount"],
            ["Consulting", "2", f"{subtotal / 2:.2f}", "20%", f"{subtotal:.2f}"],
        ]
        write_document(documents / filename, lines, rows)
        truth[filename] = {
            "document_type": "devis",
            "quote_number": reference,
            "total": subtotal * 1.2,
            "currency": "EUR",
            "validity": "30 jours",
            "page": 1 if filename.endswith(".pdf") else None,
        }
    for i, filename in enumerate(bilan_names, 1):
        french = i in (1, 3, 5)
        year = 2026 - i
        net = 250000 + (i - 1) * 10000
        revenue = 1420000 + (i - 1) * 100000
        lines = [
            "BILAN" if french else "BALANCE SHEET",
            "Societe: Societe Horizon Fictive" if french else "Company: Horizon Fictional Ltd",
            f"Exercice: {year}" if french else f"Reporting period: {year}",
            "Currency: EUR",
            "Units: euros",
        ]
        metrics = [
            ("Total actif", "Assets", 900000),
            ("Passif", "Liabilities", 400000),
            ("Capitaux propres", "Equity", 500000),
            ("Chiffre d'affaires", "Revenue", revenue),
            ("Resultat net", "Net income", net),
            ("Tresorerie", "Cash", 150000),
        ]
        rows = [["Poste" if french else "Metric", str(year)]] + [
            [fr if french else en, f"{value:.2f}"] for fr, en, value in metrics
        ]
        write_document(documents / filename, lines, rows)
        truth[filename] = {
            "document_type": "bilan",
            "net_income": net,
            "revenue": revenue,
            "currency": "EUR",
            "reporting_period": str(year),
            "page": 1 if filename.endswith(".pdf") else None,
        }
    other_samples = {
        "other_resume.pdf": [
            "CURRICULUM VITAE",
            "Camille Exemple",
            "Experience: garden design and botany.",
            "Languages: French and English.",
        ],
        "other_notes.txt": [
            "Notes de reunion",
            "Planter des arbres au printemps.",
            "Prochaine rencontre: lundi.",
        ],
        "other_random.xlsx": [
            "Plant observations",
            "Oak trees grow near the river.",
            "Birds migrate in autumn.",
        ],
        "other_readme.md": [
            "# Hiking notes",
            "Bring water and comfortable shoes.",
            "The trail follows the river.",
        ],
        "other_letter.docx": [
            "Personal letter",
            "Dear friend, thank you for the birthday card.",
            "See you next summer.",
        ],
    }
    for filename, lines in other_samples.items():
        write_document(documents / filename, lines, [])
        truth[filename] = {"document_type": "other"}
    # Extra edge fixtures exercise OCR PDFs, image encodings, spreadsheet formulas, and slides.
    scan = render_image(
        [
            "FACTURE: FAC-SCAN-001",
            "Fournisseur: Atelier Fictif",
            "Client: ABC",
            "Currency: EUR",
            "Total HT: 100.00",
            "Montant TVA: 20.00",
            "Montant TTC: 120.00",
        ],
        [],
    )
    scan.save(documents / "scanned_invoice.pdf", "PDF", resolution=150)
    for suffix in ("webp", "tiff"):
        scan.save(documents / f"scanned_invoice.{suffix}")
    Image.new("RGB", (2, 2), "white").save(documents / "tiny.png")
    (documents / "corrupted.pdf").write_bytes(b"%PDF-1.7 broken")
    (documents / "empty.txt").write_bytes(b"")
    write_document(documents / "other_page.html", ["Garden journal", "The oak tree is growing."], [])
    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "Garden project"
    slide.placeholders[1].text = "Oak trees and spring planting."
    presentation.save(documents / "other_slides.pptx")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Formulas"
    sheet.append(["Item", "Value", "Calculation"])
    sheet.append(["Example", 12, "=B2*2"])
    workbook.save(documents / "formulas.xlsx")
    (destination / "ground_truth.json").write_text(
        json.dumps(truth, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return truth


if __name__ == "__main__":
    print(f"Generated {len(generate())} benchmark documents plus edge fixtures in {FIXTURES / 'documents'}")
