import sys
from app.ingestion.pdf_parser import FinancialPDFParser
from app.rag.chunker import FinancialChunker
from app.rag.vector_store import FinancialVectorStore

if __name__ == "__main__":
    pdf_file = sys.argv[1] if len(sys.argv) > 1 else "../data/uploads/Apple_10K_2025.pdf"
    user_query = sys.argv[2] if len(sys.argv) > 2 else "What are the financial statement revenue and balance sheet items?"

    print(f"📄 Parsing {pdf_file}...")
    parser = FinancialPDFParser(pdf_file)
    doc = parser.parse()

    print("🧩 Chunking document...")
    chunker = FinancialChunker()
    chunks = chunker.chunk_document(doc)
    print(f"Created {len(chunks)} total chunks (Tables: {sum(1 for c in chunks if c.is_table)})")

    print("🗄️ Indexing into ChromaDB Vector Store...")
    vector_store = FinancialVectorStore()
    vector_store.add_chunks(chunks)

    print(f"\n🔍 Performing Hybrid Search for: '{user_query}'...")
    results = vector_store.hybrid_search(user_query, top_k=3)

    print("\n--- 🎯 RETRIEVED CONTEXT RESULTS ---")
    for idx, item in enumerate(results):
        print(f"\n[Result {idx+1}] (Type: {item['search_type']} | Page: {item['metadata']['page_number']} | Is Table: {item['metadata']['is_table']})")
        print(item['content'][:350] + "..." if len(item['content']) > 350 else item['content'])
