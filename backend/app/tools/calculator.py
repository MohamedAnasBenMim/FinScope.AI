import math
import re

from app.ingestion.extraction import parse_number
from pydantic import BaseModel


class CalculationResult(BaseModel):
    """Result payload for financial ratio calculations."""

    metric_name: str
    formula_used: str
    result_value: float
    formatted_result: str
    calculation_steps: str


class FinancialCalculator:
    """Deterministic financial calculation engine preventing LLM math hallucinations."""

    @staticmethod
    def parse_financial_number(val_str: str | float | int) -> float:
        """Parses formatted strings like '$1,250.50M', '(450)', or '24.5%' into float."""
        if isinstance(val_str, (int, float)):
            if not math.isfinite(val_str):
                raise ValueError("Financial values must be finite numbers.")
            return float(val_str)

        text = str(val_str).strip()

        value = parse_number(text)
        if value is None:
            raise ValueError("Enter a valid financial number.")
        suffix = re.search(r"\d\s*([KMB])\s*\)?$", text, re.I)
        multiplier = (
            {"K": 1000, "M": 1000000, "B": 1000000000}.get(suffix.group(1).upper(), 1) if suffix else 1
        )
        return value * multiplier

    def calculate_yoy_growth(
        self, current_period: str | float, prior_period: str | float, metric_name: str = "Metric"
    ) -> CalculationResult:
        """Calculates Year-over-Year (YoY) Growth Percentage."""
        curr = self.parse_financial_number(current_period)
        prior = self.parse_financial_number(prior_period)

        if prior == 0:
            raise ValueError("Prior period value cannot be zero for YoY calculation.")

        growth_rate = ((curr - prior) / abs(prior)) * 100
        formatted = f"{growth_rate:+.2f}%"

        return CalculationResult(
            metric_name=f"{metric_name} YoY Growth",
            formula_used=f"(({curr} - {prior}) / abs({prior})) * 100",
            result_value=round(growth_rate, 4),
            formatted_result=formatted,
            calculation_steps=f"Current: ${curr:,.2f} | Prior: ${prior:,.2f} | Growth: {formatted}",
        )

    def calculate_profit_margin(self, net_income: str | float, revenue: str | float) -> CalculationResult:
        """Calculates Profit Margin Percentage."""
        income = self.parse_financial_number(net_income)
        rev = self.parse_financial_number(revenue)

        if rev == 0:
            raise ValueError("Revenue cannot be zero for margin calculation.")

        margin = (income / rev) * 100
        formatted = f"{margin:.2f}%"

        return CalculationResult(
            metric_name="Profit Margin",
            formula_used=f"({income} / {rev}) * 100",
            result_value=round(margin, 4),
            formatted_result=formatted,
            calculation_steps=f"Net Income: ${income:,.2f} / Revenue: ${rev:,.2f} = {formatted}",
        )
