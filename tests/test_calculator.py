import pytest
from app.tools.calculator import FinancialCalculator


def test_locale_and_multiplier_calculations():
    calculator = FinancialCalculator()
    assert calculator.parse_financial_number("1 428,00 EUR") == 1428
    assert calculator.parse_financial_number("$1,250.50M") == 1250500000
    assert calculator.calculate_yoy_growth(125, 100).result_value == 25
    assert calculator.calculate_profit_margin(25, 100).result_value == 25
    with pytest.raises(ValueError):
        calculator.parse_financial_number("unknown")
    with pytest.raises(ValueError):
        calculator.calculate_profit_margin(5, 0)
