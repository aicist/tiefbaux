"""Compare Gemini 2.0 Flash vs 3.1 Flash Lite on LV parsing quality and speed."""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATABASE_URL", "sqlite:///./tiefbaux.db")
os.environ.setdefault("GEMINI_API_KEY", open(os.path.join(os.path.dirname(__file__), "..", ".env")).read().split("GEMINI_API_KEY=")[1].split("\n")[0])

from app.config import settings
from app.services.llm_parser import parse_lv_with_llm

PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "lv_test_v1.pdf")
MODELS = ["gemini-2.0-flash", "gemini-3.1-flash-lite-preview"]


def run_test(model_name: str, pdf_bytes: bytes) -> dict:
    """Run parsing with a specific model and collect results."""
    # Override model on frozen dataclass
    object.__setattr__(settings, "gemini_model", model_name)

    start = time.time()
    try:
        positions = parse_lv_with_llm(pdf_bytes)
    except Exception as e:
        return {"model": model_name, "error": str(e), "duration": time.time() - start}
    duration = time.time() - start

    material = [p for p in positions if p.position_type == "material"]
    service = [p for p in positions if p.position_type == "dienstleistung"]

    # Collect sortiment_relevant stats
    relevant_true = sum(1 for p in positions if p.parameters.sortiment_relevant is True)
    relevant_false = sum(1 for p in positions if p.parameters.sortiment_relevant is False)
    relevant_none = sum(1 for p in positions if p.parameters.sortiment_relevant is None)

    # Collect categories
    categories = {}
    for p in material:
        cat = p.parameters.product_category or "null"
        categories[cat] = categories.get(cat, 0) + 1

    # Detailed position list for comparison
    pos_details = []
    for p in positions:
        pos_details.append({
            "oz": p.ordnungszahl,
            "desc": p.description[:80],
            "type": p.position_type,
            "qty": p.quantity,
            "unit": p.unit,
            "category": p.parameters.product_category,
            "dn": p.parameters.nominal_diameter_dn,
            "sortiment": p.parameters.sortiment_relevant,
        })

    return {
        "model": model_name,
        "duration_s": round(duration, 1),
        "total": len(positions),
        "material": len(material),
        "service": len(service),
        "sortiment_true": relevant_true,
        "sortiment_false": relevant_false,
        "sortiment_none": relevant_none,
        "categories": categories,
        "positions": pos_details,
    }


def main():
    with open(PDF_PATH, "rb") as f:
        pdf_bytes = f.read()

    print(f"PDF: {PDF_PATH} ({len(pdf_bytes)} bytes)")
    print("=" * 80)

    results = []
    for i, model in enumerate(MODELS):
        if i > 0:
            print("\n  Warte 15s (Rate Limit) ...")
            time.sleep(15)
        print(f"\n>>> Testing {model} ...")
        result = run_test(model, pdf_bytes)
        results.append(result)

        if "error" in result:
            print(f"  ERROR: {result['error']}")
            continue

        print(f"  Duration: {result['duration_s']}s")
        print(f"  Positions: {result['total']} (Material: {result['material']}, DL: {result['service']})")
        print(f"  Sortiment: true={result['sortiment_true']}, false={result['sortiment_false']}, null={result['sortiment_none']}")
        print(f"  Categories: {json.dumps(result['categories'], ensure_ascii=False)}")

    # Side-by-side comparison
    if len(results) == 2 and all("error" not in r for r in results):
        r1, r2 = results
        print("\n" + "=" * 80)
        print(f"VERGLEICH: {r1['model']} vs {r2['model']}")
        print("=" * 80)
        print(f"{'Metrik':<30} {'2.0 Flash':>15} {'3.1 Flash Lite':>15}")
        print("-" * 60)
        print(f"{'Dauer':<30} {str(r1['duration_s'])+'s':>15} {str(r2['duration_s'])+'s':>15}")
        print(f"{'Positionen gesamt':<30} {r1['total']:>15} {r2['total']:>15}")
        print(f"{'Material':<30} {r1['material']:>15} {r2['material']:>15}")
        print(f"{'Dienstleistung':<30} {r1['service']:>15} {r2['service']:>15}")
        print(f"{'sortiment_relevant=true':<30} {r1['sortiment_true']:>15} {r2['sortiment_true']:>15}")
        print(f"{'sortiment_relevant=false':<30} {r1['sortiment_false']:>15} {r2['sortiment_false']:>15}")
        print(f"{'sortiment_relevant=null':<30} {r1['sortiment_none']:>15} {r2['sortiment_none']:>15}")

        # Show differences in classification
        print("\n--- UNTERSCHIEDE IN DER KLASSIFIKATION ---")
        p1_map = {p["oz"]: p for p in r1["positions"]}
        p2_map = {p["oz"]: p for p in r2["positions"]}

        all_oz = sorted(set(list(p1_map.keys()) + list(p2_map.keys())))
        diffs = 0
        for oz in all_oz:
            a = p1_map.get(oz)
            b = p2_map.get(oz)
            if a is None:
                print(f"  {oz}: NUR in 3.1 → {b['desc'][:60]} [{b['type']}, sort={b['sortiment']}]")
                diffs += 1
            elif b is None:
                print(f"  {oz}: NUR in 2.0 → {a['desc'][:60]} [{a['type']}, sort={a['sortiment']}]")
                diffs += 1
            else:
                changes = []
                if a["type"] != b["type"]:
                    changes.append(f"type: {a['type']}→{b['type']}")
                if a["category"] != b["category"]:
                    changes.append(f"cat: {a['category']}→{b['category']}")
                if a["sortiment"] != b["sortiment"]:
                    changes.append(f"sort: {a['sortiment']}→{b['sortiment']}")
                if a["dn"] != b["dn"]:
                    changes.append(f"dn: {a['dn']}→{b['dn']}")
                if a["qty"] != b["qty"]:
                    changes.append(f"qty: {a['qty']}→{b['qty']}")
                if changes:
                    print(f"  {oz}: {a['desc'][:50]} | {', '.join(changes)}")
                    diffs += 1

        if diffs == 0:
            print("  Keine Unterschiede!")
        else:
            print(f"\n  {diffs} Unterschiede gefunden.")

        # Show all positions with sortiment classification from both models
        print("\n--- ALLE MATERIAL-POSITIONEN MIT SORTIMENT-KLASSIFIKATION ---")
        print(f"{'OZ':<10} {'Beschreibung':<50} {'2.0':>6} {'3.1':>6}")
        print("-" * 75)
        for oz in all_oz:
            a = p1_map.get(oz)
            b = p2_map.get(oz)
            if (a and a["type"] == "material") or (b and b["type"] == "material"):
                desc = (a or b)["desc"][:48]
                s1 = str(a["sortiment"]) if a else "-"
                s2 = str(b["sortiment"]) if b else "-"
                marker = " <<<" if s1 != s2 else ""
                print(f"{oz:<10} {desc:<50} {s1:>6} {s2:>6}{marker}")


if __name__ == "__main__":
    main()
