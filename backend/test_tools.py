from app.tools.calculator import FinancialCalculator
from app.rag.prompts import build_rag_prompt

if __name__ == "__main__":
    print("🧮 Testing Financial Calculator Engine...")
    calc = FinancialCalculator()

    # Test YoY Growth calculation
    yoy_res = calc.calculate_yoy_growth(current_period="$1,580M", prior_period="$1,250M", metric_name="Cash Equivalents")
    print(f"✅ {yoy_res.metric_name}: {yoy_res.formatted_result}")
    print(f"   Steps: {yoy_res.calculation_steps}")

    # Test Profit Margin calculation
    margin_res = calc.calculate_profit_margin(net_income="$320.5M", revenue="$1,200M")
    print(f"✅ {margin_res.metric_name}: {margin_res.formatted_result}")
    print(f"   Steps: {margin_res.calculation_steps}")

    print("\n📜 Testing Citation Prompt Generator...")
    mock_context = [
        {
            "content": "| Line Item | 2024 |\n| Cash | $1,580M |",
            "metadata": {"filename": "Apple_10K_2025.pdf", "page_number": 1, "is_table": "True"}
        }
    ]
    prompt = build_rag_prompt(mock_context, "What is the cash value?")
    print("✅ Generated Prompt Sample:")
    print(prompt[:350] + "...\n")
