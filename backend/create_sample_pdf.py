from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from pathlib import Path

def generate_pdf():
    output_dir = Path("../data/uploads")
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / "sample_financial_report.pdf"

    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=15
    )

    story.append(Paragraph("Acme Corporation — Annual Financial Report 2024", title_style))
    story.append(Paragraph("<b>Executive Summary:</b> In fiscal year 2024, Acme Corp achieved strong financial performance across all segments. Net revenue reached $1,580.00 Million, representing a YoY growth of +26.40% compared to $1,250.00 Million in 2023.", styles['Normal']))
    story.append(Spacer(1, 15))

    data = [
        ["Financial Metric", "FY 2023 ($M)", "FY 2024 ($M)", "YoY Growth"],
        ["Total Net Revenue", "$1,250.00", "$1,580.00", "+26.40%"],
        ["Gross Profit", "$650.00", "$890.00", "+36.92%"],
        ["Operating Expenses", "$400.00", "$480.00", "+20.00%"],
        ["Net Profit / Income", "$250.00", "$320.50", "+28.20%"],
        ["Cash & Cash Equivalents", "$500.00", "$750.00", "+50.00%"]
    ]

    t = Table(data, colWidths=[160, 100, 100, 100])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e293b")),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#f8fafc")),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor("#cbd5e1")),
    ]))

    story.append(t)
    story.append(Spacer(1, 20))
    story.append(Paragraph("<b>Note:</b> Net Profit Margin for FY 2024 stands at 20.28%, demonstrating strong operational efficiency and cost discipline.", styles['Normal']))

    doc.build(story)
    print(f"✅ Generated sample financial report at: {pdf_path.resolve()}")

if __name__ == "__main__":
    generate_pdf()
