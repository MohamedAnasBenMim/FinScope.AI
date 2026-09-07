"""Exercise the running API and persist a receipt for a subsequent restart check."""

import argparse
import json
import time
from pathlib import Path

import httpx

from scripts.generate_test_documents import FIXTURES, ROOT, generate


def check(base_url: str, receipt: Path, restart_check: bool = False):
    with httpx.Client(base_url=base_url.rstrip("/"), timeout=240) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        if restart_check:
            saved = json.loads(receipt.read_text())
            ids = saved["document_ids"]
        else:
            generate()
            mapping = {
                "facture.pdf": "invoice_fr_01.pdf",
                "devis.xlsx": "devis_fr_02.xlsx",
                "bilan.pdf": "bilan_fr_01.pdf",
                "invoice_photo.jpg": "invoice_photo_en_04.jpg",
                "notes.txt": "other_notes.txt",
            }
            response = client.post(
                "/api/documents/upload",
                files=[
                    ("files", (name, (FIXTURES / "documents" / fixture).read_bytes()))
                    for name, fixture in mapping.items()
                ],
            )
            response.raise_for_status()
            assert not response.json()["errors"], response.text
            ids = {row["filename"]: row["document_id"] for row in response.json()["documents"]}
        deadline = time.monotonic() + 1500
        while True:
            statuses = {name: client.get(f"/api/documents/{id}/status").json() for name, id in ids.items()}
            assert not any(row["status"] == "FAILED" for row in statuses.values()), statuses
            if all(row["status"] == "COMPLETED" for row in statuses.values()):
                break
            if time.monotonic() > deadline:
                raise TimeoutError(f"Ingestion did not complete: {statuses}")
            print({name: row["status"] for name, row in statuses.items()}, flush=True)
            time.sleep(3)
        types = {}
        for name, id in ids.items():
            response = client.get(f"/api/documents/{id}")
            response.raise_for_status()
            types[name] = response.json()["document_type"]
        assert types == {
            "facture.pdf": "invoice",
            "devis.xlsx": "devis",
            "bilan.pdf": "bilan",
            "invoice_photo.jpg": "invoice",
            "notes.txt": "other",
        }, types
        invoice = client.get(f"/api/documents/{ids['facture.pdf']}/extraction").json()
        assert invoice["structured_data"]["total"]["value"] == 1428
        quote = client.get(f"/api/documents/{ids['devis.xlsx']}/extraction").json()
        assert quote["structured_data"]["total"]["value"] == 1320
        bilan = client.get(f"/api/documents/{ids['bilan.pdf']}/extraction").json()
        assert bilan["structured_data"]["financial_tables"]
        answers = []
        queries = [
            ("Quel est le montant total de la facture ?", [ids["facture.pdf"]], "1428", {ids["facture.pdf"]}),
            (
                "Quel est le resultat net indique dans le bilan ?",
                [ids["bilan.pdf"]],
                "250000",
                {ids["bilan.pdf"]},
            ),
            (
                "Compare le devis avec la facture.",
                [ids["facture.pdf"], ids["devis.xlsx"]],
                None,
                {ids["facture.pdf"], ids["devis.xlsx"]},
            ),
            ("What is the chief astronaut salary?", list(ids.values()), None, set()),
        ]
        for question, selected, value, expected_sources in queries:
            response = client.post("/api/chat/query", json={"question": question, "document_ids": selected})
            response.raise_for_status()
            answer = response.json()
            assert set(answer["sources_used"]) == expected_sources, (question, answer)
            if value:
                assert value in answer["answer"], answer
            if not expected_sources:
                assert answer["insufficient_evidence"], answer
            for citation in answer["citations"]:
                if citation["document_id"] in (ids["facture.pdf"], ids["bilan.pdf"]):
                    assert citation["page"] == 1
                if citation["document_id"] == ids["devis.xlsx"]:
                    assert (
                        citation["sheet"] == "Pricing" and citation["cell_range"] and citation["page"] is None
                    )
            answers.append({"question": question, **answer})
            print(f"PASS: {question}", flush=True)
        result = {
            "document_ids": ids,
            "document_types": types,
            "answers": answers,
            "restart_check": restart_check,
        }
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"Live workflow passed. Receipt: {receipt}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8001")
    parser.add_argument("--receipt", type=Path, default=ROOT / "docs/live-workflow.json")
    parser.add_argument("--restart-check", action="store_true")
    arguments = parser.parse_args()
    check(arguments.base_url, arguments.receipt, arguments.restart_check)
