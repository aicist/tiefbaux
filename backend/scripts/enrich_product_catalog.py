"""Enrich existing product catalog records with structured technical metadata.

The script focuses on two sources of truth:
1. vendor-local structured extraction data already present in the repo
2. deterministic text heuristics for existing catalog rows

This improves the matching quality without requiring new imports first.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models import Product


ROOT = Path(__file__).resolve().parents[2]
WAVIN_EXTRACTED = Path(__file__).resolve().with_name("wavin_extracted.json")
LOAD_RANK = {"A15": 1, "B125": 2, "C250": 3, "D400": 4, "E600": 5, "F900": 6}
GENERIC_SUBCATEGORIES = {"entwaesserungsrinne", "schwerlastrinne", "rinnen", "zubehoer", "zubehör"}
TITLE_SUBCATEGORY_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("Geruchsverschluss", ("geruchsverschluss",)),
    ("Schmutzfangeimer", ("schmutzfangeimer", "schmutzfang", "laubfang")),
    ("Stirnwand", ("kombistirnwand", "stirnwand", "abschlussdeckel", "enddeckel", "anfangsdeckel")),
    ("Einlaufkasten", ("einlaufkasten",)),
    ("Sinkkasten", ("sinkkasten",)),
    ("Anschlusskasten", ("anschlusskasten",)),
    ("Hofablauf", ("hofeinlauf",)),
    ("Punkteinlauf", ("punkteinlauf",)),
    ("Rost", ("laengsstabrost", "langsstabrost", "stegrost", "gitterrost", "gussrost", "rost")),
    ("Rinnenunterteil", ("rinnenunterteil",)),
    ("Revisionsschacht", ("revisionsschacht",)),
    ("Schachtunterteil", ("schachtboden", "schachtunterteil")),
    ("Schachtrohr", ("schachtrohr",)),
    ("Schachtring", ("schachtring",)),
    ("Ausgleichsring", ("auflagering", "ausgleichsring")),
    ("Schachthals/Konus", ("schaftkonus", "konus")),
    ("Entwässerungsrinne", ("rinne",)),
]


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    repl = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
    return value.strip().lower().translate(repl)


def _combined_text(product: Product) -> str:
    return " ".join(part for part in (product.artikelname, product.artikelbeschreibung) if part)


def _detect_load_class(text: str) -> str | None:
    upper = text.upper()
    matches = re.findall(r"\b([A-F])\s*[-.]?\s*(15|125|250|400|600|900)\b", upper)
    candidates = [f"{letter}{value}" for letter, value in matches if f"{letter}{value}" in LOAD_RANK]
    if not candidates:
        return None
    return max(candidates, key=lambda item: LOAD_RANK[item])


def _detect_material(text: str) -> str | None:
    checks = [
        ("polymerbeton", "Polymerbeton"),
        ("faserbeton", "Faserbeton"),
        ("glasfaserbeton", "Faserbeton"),
        ("stahlbeton", "Stahlbeton"),
        ("beton", "Beton"),
        ("gusseisen", "Gusseisen"),
        ("guss", "Gusseisen"),
        ("edelstahl", "Edelstahl"),
        ("stahl verzinkt", "Stahl"),
        ("stahl", "Stahl"),
        ("polypropylen", "PP"),
        ("pp", "PP"),
        ("pvc-u", "PVC-U"),
        ("pvc", "PVC-U"),
        ("pe-hd", "PE-HD"),
        ("hdpe", "PE-HD"),
        ("kunststoff", "Kunststoff"),
    ]
    lowered = _normalize(text)
    for needle, label in checks:
        if needle in lowered:
            return label
    return None


def _detect_system_family(product: Product) -> str | None:
    text = _normalize(_combined_text(product))
    article = _normalize(product.artikelname)

    patterns = [
        ("wavin green connect 2000", "Wavin Green Connect 2000"),
        ("green connect 2000", "Wavin Green Connect 2000"),
        ("wavin sx 400", "Wavin SX 400"),
        ("wavin xs 400", "Wavin SX 400"),
        ("sx 400", "Wavin SX 400"),
        ("xs 400", "Wavin SX 400"),
        ("wavin tegra", "Wavin Tegra"),
        ("tegra", "Wavin Tegra"),
        ("x-stream", "Wavin X-Stream"),
        ("acaro", "Wavin Acaro PP"),
        ("aco self", "ACO Self"),
        ("aco powerdrain", "ACO Powerdrain"),
        ("powerdrain", "ACO Powerdrain"),
        ("aco multiline", "ACO Multiline"),
        ("multiline", "ACO Multiline"),
        ("aco hexaline", "ACO Hexaline"),
        ("hexaline", "ACO Hexaline"),
        ("aco kerbdrain", "ACO KerbDrain"),
        ("kerbdrain", "ACO KerbDrain"),
        ("aco monoblock", "ACO Monoblock"),
        ("monoblock", "ACO Monoblock"),
        ("aco qmax", "ACO Qmax"),
        ("qmax", "ACO Qmax"),
        ("aco xtradrain", "ACO XtraDrain"),
        ("xtradrain", "ACO XtraDrain"),
        ("faserfix", "FASERFIX"),
        ("recyfix", "RECYFIX"),
        ("drainfix", "DRAINFIX"),
        ("steelfix", "STEELFIX"),
        ("kabuflex", "Kabuflex"),
    ]
    for needle, family in patterns:
        if needle in text or needle in article:
            return family
    return None


def _extract_nominal_dn(text: str) -> int | None:
    patterns = [
        r"\bDN(?:/OD)?\s*(\d{2,4})\b",
        r"\bNW\s*(\d{2,4})\b",
        r"\bNennweite\s*(\d{2,4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_connection_dns(text: str) -> str | None:
    values = {
        int(val)
        for val in re.findall(r"\bDN(?:/OD)?\s*(\d{2,4})\b", text, re.IGNORECASE)
    }
    if not values:
        return None
    return ",".join(str(v) for v in sorted(values))


def _detect_connection_type(text: str) -> str | None:
    lowered = _normalize(text)
    if "stirnseitig" in lowered and "seitlich" in lowered:
        return "stirnseitig/seitlich"
    if "steckmuffe" in lowered:
        return "Steckmuffe"
    if "doppelmuffe" in lowered:
        return "Doppelmuffe"
    if "ueberschiebmuffe" in lowered or "überschiebmuffe" in lowered:
        return "Überschiebmuffe"
    if "flansch" in lowered:
        return "Flansch"
    if "spitzende" in lowered:
        return "Spitzende"
    if "seitlich" in lowered:
        return "seitlich"
    if "senkrecht" in lowered:
        return "senkrecht"
    return None


def _detect_seal_type(text: str) -> str | None:
    lowered = _normalize(text)
    if "lippendichtung" in lowered:
        return "Lippendichtung"
    if "gleitringdichtung" in lowered:
        return "Gleitringdichtung"
    if "dichtungsfalz" in lowered:
        return "Dichtungsfalz"
    if "mit dichtung" in lowered or "dichtung" in lowered:
        return "Dichtung"
    return None


def _guess_subcategory(product: Product) -> str | None:
    title = _normalize(product.artikelname)
    combined = _normalize(_combined_text(product))

    best_label: str | None = None
    best_pos: int | None = None
    for label, needles in TITLE_SUBCATEGORY_PATTERNS:
        for needle in needles:
            pos = title.find(needle)
            if pos == -1:
                continue
            if best_pos is None or pos < best_pos:
                best_pos = pos
                best_label = label
    if best_label:
        return best_label

    for label, needles in TITLE_SUBCATEGORY_PATTERNS:
        for needle in needles:
            if needle in combined:
                return label
    return None


def _guess_category(product: Product, subcategory: str | None) -> str | None:
    sub = _normalize(subcategory)
    if sub in {"schachtunterteil", "schachtrohr", "schachtring", "schachthals/konus", "ausgleichsring", "revisionsschacht"}:
        return "Schachtbauteile"
    if sub in {"einlaufkasten", "anschlusskasten", "sinkkasten", "hofablauf", "punkteinlauf"}:
        return "Straßenentwässerung"
    if sub in {"rost", "stirnwand", "geruchsverschluss", "schmutzfangeimer", "rinnenunterteil", "entwaesserungsrinne"}:
        return "Rinnen"
    return None


def _prefer_textual_subcategory(current: str | None, guessed: str | None) -> str | None:
    if not guessed:
        return current
    if not current:
        return guessed
    current_norm = _normalize(current)
    guessed_norm = _normalize(guessed)
    if current_norm in GENERIC_SUBCATEGORIES:
        return guessed
    override_pairs = {
        ("einlaufkasten", "geruchsverschluss"),
        ("einlaufkasten", "schmutzfangeimer"),
        ("einlaufkasten", "rost"),
        ("sinkkasten", "geruchsverschluss"),
        ("anschlusskasten", "geruchsverschluss"),
        ("entwaesserungsrinne", "rost"),
        ("entwaesserungsrinne", "stirnwand"),
        ("entwaesserungsrinne", "geruchsverschluss"),
    }
    if (current_norm, guessed_norm) in override_pairs:
        return guessed
    return current


def _load_wavin_raw() -> dict[str, dict]:
    if not WAVIN_EXTRACTED.exists():
        return {}
    raw = json.loads(WAVIN_EXTRACTED.read_text(encoding="utf-8"))
    mapping: dict[str, dict] = {}
    for item in raw:
        art_nr = str(item.get("artikel_nr") or "").strip()
        if art_nr:
            mapping[f"WAV-{art_nr}"] = item
    return mapping


def _to_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _compatible_dn_from_wavin(raw: dict) -> str | None:
    dn_main = _to_int(raw.get("nennweite_dn"))
    dn_anschluss = _to_int(raw.get("dn_anschluss"))
    if dn_main and dn_anschluss and dn_main != dn_anschluss:
        return f"{dn_main},{dn_anschluss}"
    if dn_main:
        return str(dn_main)
    return None


def _update_field(product: Product, field_name: str, new_value, counters: Counter[str], *, force: bool = False) -> bool:
    if new_value in (None, "", []):
        return False
    current = getattr(product, field_name)
    if current in (None, "") or force:
        if current != new_value:
            setattr(product, field_name, new_value)
            counters[field_name] += 1
            return True
    return False


def enrich_product(product: Product, wavin_raw: dict[str, dict], counters: Counter[str]) -> bool:
    changed = False
    text = _combined_text(product)

    if product.hersteller == "Wavin GmbH":
        raw = wavin_raw.get(product.artikel_id)
        if raw:
            changed |= _update_field(product, "kategorie", raw.get("kategorie"), counters)
            changed |= _update_field(product, "unterkategorie", raw.get("unterkategorie"), counters)
            changed |= _update_field(product, "werkstoff", raw.get("werkstoff"), counters)
            changed |= _update_field(product, "nennweite_dn", _to_int(raw.get("nennweite_dn")), counters)
            changed |= _update_field(product, "nennweite_od", _to_int(raw.get("nennweite_od")), counters)
            changed |= _update_field(product, "belastungsklasse", raw.get("belastungsklasse"), counters)
            changed |= _update_field(product, "steifigkeitsklasse_sn", raw.get("steifigkeitsklasse"), counters)
            changed |= _update_field(product, "norm_primaer", raw.get("norm"), counters)
            changed |= _update_field(product, "system_familie", raw.get("system_familie"), counters)
            changed |= _update_field(product, "kompatible_dn_anschluss", _compatible_dn_from_wavin(raw), counters)

    guessed_system = _detect_system_family(product)
    guessed_material = _detect_material(text)
    guessed_dn = _extract_nominal_dn(text)
    guessed_load = _detect_load_class(text)
    guessed_connection = _detect_connection_type(text)
    guessed_seal = _detect_seal_type(text)
    guessed_dns = _extract_connection_dns(text)
    guessed_subcategory = _guess_subcategory(product)
    guessed_category = _guess_category(product, guessed_subcategory)

    if guessed_subcategory:
        refined_subcategory = _prefer_textual_subcategory(product.unterkategorie, guessed_subcategory)
        if refined_subcategory != product.unterkategorie:
            product.unterkategorie = refined_subcategory
            counters["unterkategorie"] += 1
            changed = True

    if guessed_category and product.kategorie in (None, "", "Rinnen") and _normalize(product.unterkategorie) in {"einlaufkasten", "anschlusskasten", "sinkkasten", "hofablauf", "punkteinlauf"}:
        if product.kategorie != guessed_category:
            product.kategorie = guessed_category
            counters["kategorie"] += 1
            changed = True

    changed |= _update_field(product, "system_familie", guessed_system, counters)
    changed |= _update_field(product, "werkstoff", guessed_material, counters)
    changed |= _update_field(product, "nennweite_dn", guessed_dn, counters)
    changed |= _update_field(product, "belastungsklasse", guessed_load, counters)
    changed |= _update_field(product, "verbindungstyp", guessed_connection, counters)
    changed |= _update_field(product, "dichtungstyp", guessed_seal, counters)
    changed |= _update_field(product, "kompatible_dn_anschluss", guessed_dns, counters)

    if guessed_system and not product.kompatible_systeme:
        product.kompatible_systeme = guessed_system
        counters["kompatible_systeme"] += 1
        changed = True

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich the existing product catalog.")
    parser.add_argument("--dry-run", action="store_true", help="Analyse only, do not write changes")
    args = parser.parse_args()

    wavin_raw = _load_wavin_raw()
    counters: Counter[str] = Counter()
    touched_by_vendor: Counter[str] = Counter()

    with SessionLocal() as db:
        products = list(db.scalars(select(Product).where(Product.status == "aktiv")))
        for product in products:
            if enrich_product(product, wavin_raw, counters):
                touched_by_vendor[product.hersteller or "(leer)"] += 1

        print(f"Analysed active products: {len(products)}")
        print(f"Changed products: {sum(touched_by_vendor.values())}")
        print("Changed by vendor:")
        for vendor, count in touched_by_vendor.most_common():
            print(f"  {vendor}: {count}")
        print("Updated fields:")
        for field_name, count in counters.most_common():
            print(f"  {field_name}: {count}")

        if args.dry_run:
            db.rollback()
            print("Dry run only, no changes committed.")
            return

        db.commit()
        print("Changes committed.")


if __name__ == "__main__":
    main()
