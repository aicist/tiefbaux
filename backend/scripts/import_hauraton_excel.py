"""Import selected HAURATON products from the Excel price list.

The workbook is parsed directly via XLSX XML so the script works without
additional Python packages such as openpyxl.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Product


HERSTELLER = "HAURATON"
WAEHRUNG = "EUR"
STATUS = "aktiv"
DEFAULT_INCLUDED_FAMILIES = ("FASERFIX", "RECYFIX", "DRAINFIX", "STEELFIX")
EXCLUDED_ARTICLE_TYPES = {
    "Allgemeiner Artikel",
    "Randsteine",
    "Rasengitter",
    "Retentionstank",
    "Schrauben",
}
DEFAULT_SOURCE = Path(__file__).resolve().parents[2] / "hauraton_preisliste_2026_de.xlsx"
NS = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
LOAD_RANK = {"A15": 1, "B125": 2, "C250": 3, "D400": 4, "E600": 5, "F900": 6}
FAMILY_ORDER = ("FASERFIX", "RECYFIX", "DRAINFIX", "STEELFIX", "DACHFIX", "SPORTFIX", "REWATEC", "AQUAFIX")
ARTICLE_TYPE_SUBCATEGORY = {
    "Abdeckung": "Abdeckungen",
    "Abscheider Schachtmaterial": "Schachtbauteile",
    "DRAINFIX": "Rinnen",
    "DRAINFIX CLEAN RECYFIX": "Rinnen",
    "Einlaufkasten Kombiartikel": "Punkteinläufe",
    "Knebel": "Rinnenzubehör",
    "Kombiartikel": "Rinnen",
    "Kombiartikel Punktentwässerung": "Punkteinläufe",
    "Komplettartikel": "Rinnen",
    "Monolithische Rinne": "Rinnen",
    "Punkteinläufe": "Punkteinläufe",
    "RECYFIX HICAP Rinne": "Rinnen",
    "Rinnenunterteil": "Rinnenunterteile",
    "Rinnenzubehör": "Rinnenzubehör",
    "Schlitzabdeckung": "Schlitzabdeckungen",
    "Schlitzrinne monolithisch": "Schlitzrinnen",
    "Stichkanal": "Rinnen",
    "Stirnwand": "Stirnwände",
}


@dataclass
class SourceRow:
    art_nr: str
    ean: str | None
    vertriebstext: str
    laenge_raw: str | None
    breite_raw: str | None
    hoehe_raw: str | None
    gewicht_raw: str | None
    menge_raw: str | None
    verpackung: str | None
    price_raw: str | None
    article_type: str
    mg: str | None
    angebotstext: str


def _cell_text(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        value = cell.find("main:v", NS)
        return shared_strings[int(value.text)] if value is not None and value.text else ""
    value = cell.find("main:v", NS)
    return value.text if value is not None and value.text is not None else ""


def _load_shared_strings(workbook: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in workbook.namelist():
        return []

    root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall("main:si", NS):
        values.append("".join(text.text or "" for text in item.iterfind(".//main:t", NS)))
    return values


def _load_first_sheet(workbook: zipfile.ZipFile) -> str:
    wb = ET.fromstring(workbook.read("xl/workbook.xml"))
    rels = ET.fromstring(workbook.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels}
    first_sheet = wb.find("main:sheets/main:sheet", NS)
    if first_sheet is None:
        raise ValueError("Workbook contains no sheets")
    rel_id = first_sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
    target = rel_map[rel_id]
    return f"xl/{target}"


def iter_source_rows(path: Path) -> Iterable[SourceRow]:
    with zipfile.ZipFile(path) as workbook:
        shared_strings = _load_shared_strings(workbook)
        sheet = ET.fromstring(workbook.read(_load_first_sheet(workbook)))
        rows = sheet.find("main:sheetData", NS)
        if rows is None:
            return

        for row_index, row in enumerate(rows.findall("main:row", NS), start=1):
            values: dict[str, str] = {}
            for cell in row.findall("main:c", NS):
                ref = cell.attrib.get("r", "")
                col = re.match(r"[A-Z]+", ref)
                if not col:
                    continue
                values[col.group(0)] = _cell_text(cell, shared_strings).strip()

            if row_index == 1:
                continue

            def get(column: str) -> str | None:
                value = values.get(column, "").strip()
                return value or None

            art_nr = get("A")
            name = get("C")
            article_type = get("K")
            offer_text = get("M")
            if not art_nr or not name or not article_type or not offer_text:
                continue

            yield SourceRow(
                art_nr=art_nr,
                ean=get("B"),
                vertriebstext=name,
                laenge_raw=get("D"),
                breite_raw=get("E"),
                hoehe_raw=get("F"),
                gewicht_raw=get("G"),
                menge_raw=get("H"),
                verpackung=get("I"),
                price_raw=get("J"),
                article_type=article_type,
                mg=get("L"),
                angebotstext=offer_text,
            )


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    if not match:
        return None
    parsed = _to_float(match.group(0))
    return int(round(parsed)) if parsed is not None else None


def _pick_richer(existing: SourceRow, candidate: SourceRow) -> SourceRow:
    return SourceRow(
        art_nr=existing.art_nr,
        ean=existing.ean or candidate.ean,
        vertriebstext=existing.vertriebstext if len(existing.vertriebstext) >= len(candidate.vertriebstext) else candidate.vertriebstext,
        laenge_raw=existing.laenge_raw or candidate.laenge_raw,
        breite_raw=existing.breite_raw or candidate.breite_raw,
        hoehe_raw=existing.hoehe_raw or candidate.hoehe_raw,
        gewicht_raw=existing.gewicht_raw or candidate.gewicht_raw,
        menge_raw=existing.menge_raw or candidate.menge_raw,
        verpackung=existing.verpackung or candidate.verpackung,
        price_raw=existing.price_raw or candidate.price_raw,
        article_type=existing.article_type if len(existing.article_type) >= len(candidate.article_type) else candidate.article_type,
        mg=existing.mg or candidate.mg,
        angebotstext=existing.angebotstext if len(existing.angebotstext) >= len(candidate.angebotstext) else candidate.angebotstext,
    )


def _detect_family(text: str) -> str | None:
    upper = text.upper()
    for family in FAMILY_ORDER:
        if family in upper:
            return family
    return None


def _standardize_load_class(text: str) -> str | None:
    matches = re.findall(r"\b([A-F])\s*([0-9]{2,3})\b", text.upper())
    if not matches:
        return None
    classes = [f"{letter}{value}" for letter, value in matches if f"{letter}{value}" in LOAD_RANK]
    if not classes:
        return None
    return max(classes, key=lambda item: LOAD_RANK[item])


def _extract_norms(text: str) -> tuple[str | None, str | None]:
    upper = text.upper()
    norms: list[str] = []
    if "EN 1433" in upper:
        norms.append("DIN EN 1433")
    if "DIN 19580" in upper:
        norms.append("DIN 19580")
    for match in re.findall(r"\bDIN(?:\s+EN)?\s+\d+(?:-\d+)?\b", upper):
        value = re.sub(r"\s+", " ", match).strip()
        if value not in norms:
            norms.append(value)
    primary = norms[0] if norms else None
    secondary = norms[1] if len(norms) > 1 else None
    return primary, secondary


def _extract_material(text: str) -> str | None:
    checks = [
        ("faserbewehrtem beton", "Faserbeton"),
        ("faserbewehrter beton", "Faserbeton"),
        ("beton", "Beton"),
        ("recyceltem polypropylen", "PP"),
        ("polypropylen", "PP"),
        ("pe-hd", "PE-HD"),
        ("edelstahl", "Edelstahl"),
        ("aluminium", "Aluminium"),
        ("stahl", "Stahl"),
        ("guss", "Gusseisen"),
        ("kunststoff", "Kunststoff"),
    ]
    lowered = text.lower()
    for needle, label in checks:
        if needle in lowered:
            return label
    return None


def _extract_nominal_size(text: str) -> int | None:
    patterns = [
        r"\bNennweite\s+(\d{2,4})\b",
        r"\b(?:KS|STANDARD|PLUS|PRO|SUPER|MONOTEC|POINT|SLOT|FSU|RNC|HICAP)\s+(\d{2,4})\b",
        r"\bDN(?:/OD)?\s*(\d{2,4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _extract_connection_dns(text: str) -> str | None:
    values = {
        int(match)
        for match in re.findall(r"\bDN(?:/OD)?\s*(\d{2,4})\b", text, re.IGNORECASE)
    }
    if not values:
        return None
    return ",".join(str(value) for value in sorted(values))


def _extract_connection_type(text: str) -> str | None:
    lowered = text.lower()
    if "stirnseitig" in lowered and "seitlich" in lowered:
        return "stirnseitig/seitlich"
    if "stirnseitig" in lowered:
        return "stirnseitig"
    if "seitlich" in lowered:
        return "seitlich"
    if "senkrecht" in lowered:
        return "senkrecht"
    return None


def _extract_seal_type(text: str) -> str | None:
    lowered = text.lower()
    if "dichtungsfalz" in lowered:
        return "Dichtungsfalz"
    if "mit dichtung" in lowered or "kg-muffe mit dichtung" in lowered:
        return "Dichtung"
    return None


def _article_category(article_type: str) -> str:
    if article_type in {"Punkteinläufe", "Einlaufkasten Kombiartikel", "Kombiartikel Punktentwässerung"}:
        return "Straßenentwässerung"
    if article_type in {"Abscheider Schachtmaterial"}:
        return "Schachtbauteile"
    if article_type in {"Retentionstank"}:
        return "Versickerung"
    return "Rinnen"


def _article_subcategory(article_type: str) -> str:
    return ARTICLE_TYPE_SUBCATEGORY.get(article_type, article_type)


def _price_unit(row: SourceRow) -> str:
    text = f"{row.vertriebstext} {row.angebotstext}".lower()
    if "meterware" in text:
        return "m"
    return "Stk"


def _is_relevant(row: SourceRow, included_families: set[str]) -> bool:
    combined = f"{row.vertriebstext} {row.angebotstext}"
    family = _detect_family(combined)
    if family not in included_families:
        return False
    if row.article_type in EXCLUDED_ARTICLE_TYPES:
        return False
    return True


def _build_product(row: SourceRow) -> Product:
    combined = f"{row.vertriebstext} {row.angebotstext}"
    family = _detect_family(combined)
    norm_primary, norm_secondary = _extract_norms(combined)
    compatible_dns = _extract_connection_dns(combined)

    return Product(
        artikel_id=f"HAUR-{row.art_nr}",
        ean_gtin=row.ean,
        hersteller=HERSTELLER,
        hersteller_artikelnr=row.art_nr,
        artikelname=row.vertriebstext,
        artikelbeschreibung=row.angebotstext,
        kategorie=_article_category(row.article_type),
        unterkategorie=_article_subcategory(row.article_type),
        werkstoff=_extract_material(combined),
        nennweite_dn=_extract_nominal_size(combined),
        laenge_mm=_to_int(row.laenge_raw),
        breite_mm=_to_int(row.breite_raw),
        hoehe_mm=_to_int(row.hoehe_raw),
        gewicht_kg=_to_float(row.gewicht_raw),
        belastungsklasse=_standardize_load_class(combined),
        norm_primaer=norm_primary,
        norm_sekundaer=norm_secondary,
        system_familie=family,
        verbindungstyp=_extract_connection_type(combined),
        dichtungstyp=_extract_seal_type(combined),
        kompatible_dn_anschluss=compatible_dns,
        kompatible_systeme=family,
        einsatzbereich="Oberflächenentwässerung",
        vk_listenpreis_netto=_to_float(row.price_raw),
        waehrung=WAEHRUNG,
        preiseinheit=_price_unit(row),
        status=STATUS,
    )


def _load_rows(path: Path, included_families: set[str]) -> tuple[list[SourceRow], dict[str, int]]:
    deduped: dict[str, SourceRow] = {}
    stats = Counter[str]()
    for row in iter_source_rows(path):
        stats["source_rows"] += 1
        if not _is_relevant(row, included_families):
            stats["filtered_out"] += 1
            continue
        if row.art_nr in deduped:
            deduped[row.art_nr] = _pick_richer(deduped[row.art_nr], row)
            stats["dedupe_hits"] += 1
        else:
            deduped[row.art_nr] = row
        if not row.price_raw:
            stats["missing_price"] += 1
    return list(deduped.values()), dict(stats)


def run_import(source: Path, included_families: set[str], dry_run: bool, replace_existing: bool) -> None:
    rows, stats = _load_rows(source, included_families)
    products = [_build_product(row) for row in rows]

    family_counts = Counter(product.system_familie or "(leer)" for product in products)
    type_counts = Counter(product.unterkategorie or "(leer)" for product in products)
    missing_price = sum(1 for product in products if product.vk_listenpreis_netto is None)
    missing_dn = sum(1 for product in products if product.nennweite_dn is None)

    print(f"Source file: {source}")
    print(f"Relevant rows after filtering/deduplication: {len(products)}")
    print(f"Filtered out rows: {stats.get('filtered_out', 0)}")
    print(f"Duplicate merges: {stats.get('dedupe_hits', 0)}")
    print(f"Products without price: {missing_price}")
    print(f"Products without nominal size: {missing_dn}")
    print("Families:")
    for family, count in family_counts.most_common():
        print(f"  {family}: {count}")
    print("Top subcategories:")
    for subcategory, count in type_counts.most_common(12):
        print(f"  {subcategory}: {count}")

    if dry_run:
        return

    db = SessionLocal()
    try:
        if replace_existing:
            deleted = db.execute(delete(Product).where(Product.hersteller == HERSTELLER)).rowcount or 0
            print(f"Deleted existing {HERSTELLER} products: {deleted}")

        existing = set(
            db.scalars(select(Product.artikel_id).where(Product.hersteller == HERSTELLER)).all()
        )

        added = 0
        skipped = 0
        for product in products:
            if product.artikel_id in existing:
                skipped += 1
                continue
            db.add(product)
            existing.add(product.artikel_id)
            added += 1

        db.commit()
        print(f"Import complete: {added} added, {skipped} skipped")
        print(f"Total {HERSTELLER} products in DB: {len(existing)}")
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import HAURATON products from Excel price list")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Path to HAURATON XLSX file")
    parser.add_argument(
        "--include-family",
        action="append",
        dest="include_families",
        help="Repeatable family filter. Defaults to FASERFIX, RECYFIX, DRAINFIX, STEELFIX.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only analyze the file, do not write to the DB")
    parser.add_argument("--replace", action="store_true", help="Delete existing HAURATON rows before importing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    included_families = {
        value.strip().upper() for value in (args.include_families or DEFAULT_INCLUDED_FAMILIES) if value.strip()
    }
    if not args.source.exists():
        raise FileNotFoundError(f"Source file not found: {args.source}")
    run_import(args.source, included_families, dry_run=args.dry_run, replace_existing=args.replace)


if __name__ == "__main__":
    main()
