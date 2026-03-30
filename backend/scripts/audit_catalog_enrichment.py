"""Audit current catalog enrichment quality and flag suspicious assignments."""

from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict

from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models import Product
from scripts.enrich_product_catalog import (  # type: ignore
    _combined_text,
    _detect_load_class,
    _detect_material,
    _detect_system_family,
    _extract_connection_dns,
    _extract_nominal_dn,
    _guess_subcategory,
    _load_wavin_raw,
)


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    repl = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})
    return value.strip().lower().translate(repl)


def main() -> None:
    wavin_raw = _load_wavin_raw()
    suspicious: list[tuple[str, str, str, str, str]] = []
    field_quality = Counter()
    field_suspicious = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    with SessionLocal() as db:
        products = list(db.scalars(select(Product).where(Product.status == "aktiv")))
        for product in products:
            combined = _combined_text(product)
            normalized_subcategory = _normalize(product.unterkategorie)
            guessed_subcategory = _guess_subcategory(product)
            guessed_system = _detect_system_family(product)
            guessed_material = _detect_material(combined)
            guessed_dn = _extract_nominal_dn(combined)
            guessed_load = _detect_load_class(combined)
            guessed_dns = _extract_connection_dns(combined)

            if product.hersteller == "Wavin GmbH" and product.artikel_id in wavin_raw:
                field_quality["wavin_structured_rows"] += 1

            if product.system_familie:
                field_quality["system_present"] += 1
                if guessed_system and _normalize(product.system_familie) != _normalize(guessed_system):
                    field_suspicious["system_family_conflict"] += 1
                    if len(examples["system_family_conflict"]) < 12:
                        examples["system_family_conflict"].append(
                            f"{product.artikel_id}: {product.system_familie} != {guessed_system} | {product.artikelname}"
                        )

            if product.werkstoff:
                field_quality["material_present"] += 1
                if guessed_material and _normalize(product.werkstoff) != _normalize(guessed_material):
                    field_suspicious["material_conflict"] += 1
                    if len(examples["material_conflict"]) < 12:
                        examples["material_conflict"].append(
                            f"{product.artikel_id}: {product.werkstoff} != {guessed_material} | {product.artikelname}"
                        )

            if product.nennweite_dn is not None:
                field_quality["dn_present"] += 1
                if guessed_dn and product.nennweite_dn != guessed_dn:
                    field_suspicious["dn_conflict"] += 1
                    if len(examples["dn_conflict"]) < 12:
                        examples["dn_conflict"].append(
                            f"{product.artikel_id}: DN {product.nennweite_dn} != {guessed_dn} | {product.artikelname}"
                        )

            if product.belastungsklasse:
                field_quality["load_present"] += 1
                if guessed_load and _normalize(product.belastungsklasse) != _normalize(guessed_load):
                    field_suspicious["load_conflict"] += 1
                    if len(examples["load_conflict"]) < 12:
                        examples["load_conflict"].append(
                            f"{product.artikel_id}: {product.belastungsklasse} != {guessed_load} | {product.artikelname}"
                        )

            if product.kompatible_dn_anschluss:
                field_quality["connection_dn_present"] += 1
                if guessed_dns and product.kompatible_dn_anschluss != guessed_dns:
                    field_suspicious["connection_dn_conflict"] += 1
                    if len(examples["connection_dn_conflict"]) < 12:
                        examples["connection_dn_conflict"].append(
                            f"{product.artikel_id}: {product.kompatible_dn_anschluss} != {guessed_dns} | {product.artikelname}"
                        )

            if guessed_subcategory and normalized_subcategory and normalized_subcategory != _normalize(guessed_subcategory):
                suspicious.append((
                    product.artikel_id,
                    product.hersteller or "",
                    product.unterkategorie or "",
                    guessed_subcategory,
                    product.artikelname,
                ))

    print(f"Suspicious subcategory assignments: {len(suspicious)}")
    for artikel_id, hersteller, current, guessed, title in suspicious[:40]:
        print(f"{artikel_id}\t{hersteller}\t{current}\t->\t{guessed}\t|\t{title}")

    print("\nField coverage:")
    for key, value in sorted(field_quality.items()):
        print(f"{key}: {value}")

    print("\nField conflicts:")
    for key, value in sorted(field_suspicious.items()):
        print(f"{key}: {value}")
        for line in examples[key]:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
