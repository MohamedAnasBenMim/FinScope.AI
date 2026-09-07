from pydantic import BaseModel, Field


class Source(BaseModel):
    document_id: str
    filename: str
    block_id: str | None = None
    page: int | None = None
    table_id: str | None = None
    sheet: str | None = None
    cell_range: str | None = None
    section: str | None = None
    slide_number: int | None = None
    excerpt: str


class SourcedValue(BaseModel):
    value: float | str
    source: Source


class Party(BaseModel):
    name: SourcedValue | None = None
    address: SourcedValue | None = None
    tax_id: SourcedValue | None = None
    registration_number: SourcedValue | None = None
    email: SourcedValue | None = None
    phone: SourcedValue | None = None


class LineItem(BaseModel):
    description: SourcedValue | None = None
    quantity: SourcedValue | None = None
    unit: SourcedValue | None = None
    unit_price: SourcedValue | None = None
    tax_rate: SourcedValue | None = None
    amount: SourcedValue | None = None


class CommercialExtraction(BaseModel):
    supplier: Party = Field(default_factory=Party)
    customer: Party = Field(default_factory=Party)
    currency: SourcedValue | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: SourcedValue | None = None
    tax_amount: SourcedValue | None = None
    total: SourcedValue | None = None
    payment_terms: SourcedValue | None = None
    warnings: list[str] = Field(default_factory=list)


class InvoiceExtraction(CommercialExtraction):
    invoice_number: SourcedValue | None = None
    invoice_date: SourcedValue | None = None
    due_date: SourcedValue | None = None
    iban: SourcedValue | None = None


class QuoteExtraction(CommercialExtraction):
    quote_number: SourcedValue | None = None
    quote_date: SourcedValue | None = None
    valid_until: SourcedValue | None = None
    validity: SourcedValue | None = None
    notes: SourcedValue | None = None


class FinancialTable(BaseModel):
    rows: list[list[str]]
    source: Source


class BilanExtraction(BaseModel):
    company_name: SourcedValue | None = None
    reporting_period: SourcedValue | None = None
    currency: SourcedValue | None = None
    units: SourcedValue | None = None
    assets: SourcedValue | None = None
    current_assets: SourcedValue | None = None
    non_current_assets: SourcedValue | None = None
    liabilities: SourcedValue | None = None
    current_liabilities: SourcedValue | None = None
    non_current_liabilities: SourcedValue | None = None
    equity: SourcedValue | None = None
    revenue: SourcedValue | None = None
    operating_income: SourcedValue | None = None
    net_income: SourcedValue | None = None
    cash: SourcedValue | None = None
    financial_tables: list[FinancialTable] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
