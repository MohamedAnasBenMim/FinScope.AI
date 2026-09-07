"""Extensible, conservative bilingual classification with inspectable signals."""

import re
import unicodedata
from dataclasses import dataclass

from app.ingestion.normalized import Classification, NormalizedDocument


def fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


@dataclass(frozen=True)
class ClassRule:
    name: str
    title: str
    identifier: str
    vocabulary: tuple[str, ...]


RULES = [
    ClassRule(
        "invoice",
        r"^(?:facture|invoice|bill)(?:\s*(?:n[o°.]|number|#|:|[A-Z]{2,}-|\d)|\s*$)",
        r"\b(?:invoice number|numero de facture|facture n|invoice #|FAC-\d|INV-\d)",
        (
            r"\b(?:facture|invoice)\b",
            r"\b(?:ttc|total due|amount due|grand total)\b",
            r"\b(?:tva|vat|tax)\b",
            r"\b(?:fournisseur|supplier|bill from)\b",
            r"\b(?:client|customer|bill to)\b",
            r"\b(?:echeance|due date)\b",
        ),
    ),
    ClassRule(
        "devis",
        r"^(?:devis|quotation|quote|estimate|proposition commerciale|price offer)\b",
        r"\b(?:quote number|quotation number|numero de devis|devis n|DEV-\d|QUO-\d)",
        (
            r"\b(?:devis|quotation|quote|estimate)\b",
            r"\b(?:validite|valid until|validity|bon pour accord)\b",
            r"\b(?:ttc|grand total|total)\b",
            r"\b(?:tva|vat|tax)\b",
            r"\b(?:fournisseur|supplier)\b",
            r"\b(?:client|customer)\b",
        ),
    ),
    ClassRule(
        "bilan",
        r"^(?:bilan|balance sheet|financial statements?|annual (?:financial )?report|rapport financier|compte de resultat|income statement)\b",
        r"\b(?:exercice|reporting period|fiscal year|financial year)\b",
        (
            r"\b(?:actif|assets)\b",
            r"\b(?:passif|liabilities)\b",
            r"\b(?:capitaux propres|equity)\b",
            r"\b(?:resultat net|net income|net profit)\b",
            r"\b(?:chiffre d.affaires|revenue)\b",
            r"\b(?:tresorerie|cash)\b",
        ),
    ),
]


class DocumentClassifier:
    def __init__(self, threshold: float = 0.65, rules: list[ClassRule] | None = None):
        self.threshold = threshold
        self.rules = rules or RULES

    def classify(self, doc: NormalizedDocument) -> Classification:
        text = fold("\n".join(b.text for b in doc.blocks))
        lines = [line.strip(" #|\t") for line in text.splitlines()]
        candidates = []
        for rule in self.rules:
            signals = []
            score = 0.0
            if any(re.search(rule.title, line, re.I) for line in lines):
                score += 0.50
                signals.append(f"{rule.name}: document title/heading")
            if re.search(rule.identifier, text, re.I):
                score += 0.16
                signals.append(f"{rule.name}: reference/reporting period")
            vocabulary_hits = [pattern for pattern in rule.vocabulary if re.search(pattern, text)]
            score += min(0.30, len(vocabulary_hits) * 0.06)
            signals.extend(f"vocabulary: {pattern}" for pattern in vocabulary_hits)
            if any(b.type in ("table", "spreadsheet") for b in doc.blocks) and len(vocabulary_hits) >= 2:
                score += 0.04
                signals.append("structured table and financial vocabulary")
            candidates.append((min(score, 0.99), rule.name, signals))
        candidates.sort(reverse=True)
        confidence, name, signals = candidates[0]
        ambiguous = confidence >= self.threshold and candidates[1][0] >= confidence - 0.12
        if confidence < self.threshold or ambiguous:
            reason = (
                "Conflicting class signals."
                if ambiguous
                else f"Best candidate {name} ({confidence:.2f}) is below threshold {self.threshold:.2f}."
            )
            return Classification(
                document_type="other", confidence=round(confidence, 3), reason=reason, signals=signals
            )
        return Classification(
            document_type=name,
            confidence=round(confidence, 3),
            reason="Content, headings and financial fields support this class.",
            signals=signals,
        )
