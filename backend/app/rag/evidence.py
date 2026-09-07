import re

from app.ingestion.classifier import fold


def requested_metric_pattern(question: str) -> str | None:
    question = fold(question)
    if re.search(r"resultat net|net (?:income|profit)", question):
        return r"resultat net|net (?:income|profit)"
    if re.search(r"chiffre d.affaires|revenue", question):
        return r"chiffre d.affaires|(?:net )?revenue"
    if re.search(r"validite|validity|valid until", question):
        return r"validite|validity|valid until"
    if re.search(r"ttc|total|amount due", question):
        return r"montant ttc|total ttc|grand total|amount due|total due|(?<!sub)\btotal\s*[:|]"
    return None


def relevant_metric(quote: str, pattern: str | None) -> bool:
    return pattern is None or bool(re.search(pattern, fold(quote)))
