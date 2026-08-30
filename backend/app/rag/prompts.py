SYSTEM_CITATION_PROMPT = """You are FinScope.AI, an expert financial analyst assistant.
Your job is to answer user financial questions strictly using the retrieved context provided below.

RULES:
1. STRICT GROUNDING: Rely ONLY on the facts, numbers, and tables present in the retrieved context. Do not invent financial metrics.
2. SOURCE CITATIONS: Every claim or extracted metric MUST be followed by an inline citation badge referencing the source document and page number, formatted exactly as:
   `[Source: <filename>, Page <page_number>]`
3. TABLE DATA: When referencing table metrics, preserve tabular precision.
4. CALCULATION ACCURACY: State explicit formulas used for any growth or ratio metrics.

Retrieved Context:
{retrieved_context}

User Question:
{user_query}

FinScope.AI Response:"""


def build_rag_prompt(retrieved_items: list[dict], user_query: str) -> str:
    """Formats retrieved vector and BM25 chunks into a grounded LLM prompt."""
    context_blocks = []

    for idx, item in enumerate(retrieved_items, start=1):
        meta = item["metadata"]
        filename = meta.get("filename", "Document")
        page_num = meta.get("page_number", "N/A")
        is_table = "Table" if meta.get("is_table") == "True" else "Text"

        header = f"--- [Block {idx} | File: {filename} | Page: {page_num} | Type: {is_table}] ---"
        context_blocks.append(f"{header}\n{item['content']}")

    full_context = "\n\n".join(context_blocks)
    return SYSTEM_CITATION_PROMPT.format(
        retrieved_context=full_context,
        user_query=user_query
    )
