import hashlib
import math
import re
from collections import Counter

from app.ingestion.classifier import fold
from qdrant_client.models import SparseVector

STOPWORDS = set(
    "the a an is are was were of for with in on and or to what which how much does do from between de du des le la les un une et ou en au aux pour quel quelle quels quelles est sont a dans avec combien indique indiquee montant document documents please me tell dit donne".split()
)
CONCEPTS = {
    "facture": "invoice",
    "factures": "invoice",
    "invoices": "invoice",
    "bills": "invoice",
    "devis": "quote",
    "quotation": "quote",
    "quotations": "quote",
    "estimate": "quote",
    "bilan": "statement",
    "bilans": "statement",
    "financial": "statement",
    "resultat": "income",
    "benefice": "income",
    "profit": "income",
    "revenu": "revenue",
    "fournisseur": "supplier",
    "fournisseurs": "supplier",
    "client": "customer",
    "validite": "validity",
    "ttc": "total",
    "assets": "actif",
    "liabilities": "passif",
    "compare": "compare",
    "comparer": "compare",
    "comparaison": "compare",
}


def tokens(text: str) -> list[str]:
    normalized = fold(text)
    normalized = re.sub(r"chiffre d.affaires", "revenue", normalized)
    raw = re.findall(r"[a-z0-9]+(?:[-./][a-z0-9]+)*", normalized)
    return [
        CONCEPTS.get(token, token)
        for token in raw
        if token not in STOPWORDS and (len(token) > 1 or token.isdigit())
    ]


def sparse_vector(text: str) -> SparseVector:
    counts = Counter(tokens(text))
    hashed = Counter()
    for word, count in counts.items():
        # Stable 32-bit vocabulary; collisions are possible but rare and do not alter stored text.
        index = int.from_bytes(hashlib.blake2s(word.encode(), digest_size=4).digest(), "big")
        hashed[index] += 1 + math.log(count)
    return SparseVector(indices=sorted(hashed), values=[float(hashed[index]) for index in sorted(hashed)])
