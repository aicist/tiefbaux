"""Import Wavin product catalog PDF into the TiefbauX database using Gemini for extraction."""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
import pdfplumber

# Add backend to path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import SessionLocal, engine
from app.models import Base, Product

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PAGE_BATCH_SIZE = 3
PAGE_OVERLAP = 0

SYSTEM_INSTRUCTION = (
    "Du bist ein Datenbank-Experte fuer Tiefbau-Produkte. "
    "Du extrahierst Produktdaten aus Preislisten-Tabellen.\n\n"
    "Extrahiere ALLE Produkte aus den Tabellen auf diesen Seiten. "
    "Jede Zeile in einer Produkttabelle ist ein separates Produkt.\n\n"
    "Gib ein JSON-Array zurueck. Jedes Objekt hat diese Felder:\n"
    "- artikel_nr: string (die 7-stellige Artikelnummer, z.B. '3042330')\n"
    "- artikelname: string (vollstaendiger Name, z.B. 'Wavin KG Rohr DN110 1000mm' oder "
    "'Wavin TS DOQ PE-Druckrohr OD110 SDR11 12m Trinkwasser')\n"
    "- artikelbeschreibung: string (Tabellenbezeichnung + Produktgruppe + Medium + SDR/PN, z.B. "
    "'KG Mehrschicht Rohr KG-EM PVC DN110 L=1000mm' oder "
    "'Wavin TS DOQ PE 100-RC Druckrohr Trinkwasser SDR 11 PN 16bar Stange 12m OD 110mm')\n"
    "- kategorie: string (eine von: Kanalrohre, Schachtbauteile, Schachtabdeckungen, "
    "Formstuecke, Dichtungen & Zubehoer, Strassenentwässerung, Rinnen, "
    "Versickerung, Regenwasser, Kabelschutz, Gasrohre, Wasserrohre, Druckrohre)\n"
    "  WICHTIG fuer Druckrohrsysteme:\n"
    "  - Wenn das Medium 'Gas' ist oder die Tabellenueberschrift 'Gas' enthaelt → kategorie = 'Gasrohre'\n"
    "  - Wenn das Medium 'Trinkwasser' ist → kategorie = 'Wasserrohre'\n"
    "  - Wenn das Medium 'Abwasser' ist (Druckrohr, nicht KG!) → kategorie = 'Druckrohre'\n"
    "  - PE-Boegen/Universalboegen die fuer alle Medien gelten → kategorie = 'Formstuecke'\n"
    "  - PVC-U Druckrohre fuer Trinkwasser → kategorie = 'Wasserrohre'\n"
    "  - PVC-U Druckrohr Formteile (Boegen, Muffen) → kategorie = 'Formstuecke'\n"
    "  - PVC Zubehoer (Dichtungen, Gleitmittel) → kategorie = 'Dichtungen & Zubehoer'\n"
    "- unterkategorie: string (z.B. 'KG-Rohre', 'KG-Boegen', 'PE-Druckrohr', 'PE-Bogen', "
    "'PVC-Druckrohr', 'PVC-Druckrohr-Bogen', 'PVC-Muffe', 'Dichtung', "
    "'Tegra Schachtboden', 'Strassenablauf', etc.)\n"
    "- werkstoff: string | null (PVC-U, PP, PE, PE 100, PE 100-RC, PP-HM, PP-MD, Beton, Guss, etc.)\n"
    "- nennweite_dn: integer | null (DN-Wert bei PVC-U Druckrohren: DN 80, 100, 125, etc. "
    "Bei PE-Rohren: NICHT den OD-Wert hier eintragen, sondern null lassen!)\n"
    "- nennweite_od: integer | null (Aussendurchmesser OD in mm, besonders bei PE-Druckrohren: "
    "32, 40, 50, 63, 75, 90, 110, 125, 140, 160, 180, 200, 225, 250, 280, 315, 355, 400, 450, 500)\n"
    "- laenge_mm: integer | null (Laenge in mm. Baulaenge 6m = 6000, 12m = 12000. "
    "Bei Ringbund 100m = 100000, 200m = 200000)\n"
    "- hoehe_mm: integer | null (Hoehe H in mm wenn angegeben)\n"
    "- wandstaerke_mm: number | null (Wandstaerke s in mm, z.B. 3.0, 4.6, 10.0)\n"
    "- gewicht_kg: number | null (Gewicht kg/m oder kg/Stk)\n"
    "- belastungsklasse: string | null (A15, B125, C250, D400, E600, F900)\n"
    "- steifigkeitsklasse: string | null (SN4, SN8, SN16)\n"
    "- sdr: string | null (SDR-Wert: 'SDR 11', 'SDR 17', etc.)\n"
    "- druckstufe: string | null (Druckstufe: 'PN 10', 'PN 12.5', 'PN 16', etc.)\n"
    "- medium: string | null ('Trinkwasser', 'Gas', 'Abwasser')\n"
    "- lieferform: string | null ('Stange 6m', 'Stange 12m', 'Ringbund', 'Ringbund 100m')\n"
    "- norm: string | null (DIN EN 12201-2, DIN EN 1555-2, DIN EN 1452, DIN EN 13476-2, etc.)\n"
    "- preis_eur_stk: number | null (Preis in EUR/Stk bei Boegen und Formteilen)\n"
    "- preis_eur_m: number | null (Preis in EUR/m bei Rohren)\n"
    "- verpackungseinheit: integer | null (VPE Stk oder m)\n"
    "- winkel_grad: integer | null (Winkel bei Boegen: 11, 22, 30, 45, 90)\n"
    "- dn_anschluss: integer | null (zweiter DN bei Abzweigen/Reduzierstuecken)\n"
    "- system_familie: string | null ('Wavin KG', 'Wavin Tegra', 'Wavin TS DOQ', "
    "'Wavin SafeTech RC', 'Wavin PE 100-RC Druckrohr', 'Wavin PE 100 Druckrohr', "
    "'Wavin PE 100-RC Universalbogen', 'Wavin PVC Druckrohr', etc.)\n\n"
    "REGELN:\n"
    "- Ueberspringe Ueberschriften, Bildseiten und Textbloecke ohne Produkttabellen\n"
    "- Wenn eine Zeile 'auf Anfrage' statt Artikel-Nr hat, setze artikel_nr auf null\n"
    "- Preise als Zahl ohne Waehrungssymbol (z.B. 15.75 nicht '15,75 EUR')\n"
    "- Deutsche Kommazahlen umwandeln: '15,75' -> 15.75\n"
    "- Bei KG-Rohren: Laenge steht oft als L-Spalte in mm (1.000 = 1000mm, 2.000 = 2000mm, 5.000 = 5000mm)\n"
    "- Bei PE-Druckrohren: OD ist der Aussendurchmesser, NICHT DN! Trage OD in nennweite_od ein.\n"
    "- Jede Tabellenzeile = ein Produkt, auch wenn Bezeichnungen sich wiederholen\n"
    "- WICHTIG: Achte auf den Tabellentitel fuer Medium-Zuordnung: 'Trinkwasser', 'Gas', 'Abwasser'\n"
    "- Gib NUR das JSON-Array zurueck, keine Erklaerung\n"
    "- Wenn die Seiten keine Produkttabellen enthalten, gib ein leeres Array [] zurueck"
)


def extract_pages(pdf_path: str) -> list[str]:
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
    return pages


def create_batches(pages: list[str]) -> list[tuple[int, list[str]]]:
    if not pages:
        return []
    batches: list[tuple[int, list[str]]] = []
    start = 0
    while start < len(pages):
        end = min(start + PAGE_BATCH_SIZE, len(pages))
        batches.append((start, pages[start:end]))
        next_start = end - PAGE_OVERLAP
        if next_start <= start:
            break
        start = next_start
    return batches


def call_gemini(page_texts: list[str], page_offset: int) -> list[dict[str, Any]]:
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY not configured")

    pages_block = ""
    for i, text in enumerate(page_texts):
        pages_block += f"\n--- Seite {page_offset + i + 1} ---\n{text}\n"

    prompt = f"Extrahiere alle Produkte aus diesen Preislisten-Seiten:\n{pages_block}"

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "maxOutputTokens": 65536,
        },
    }

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )

    with httpx.Client(timeout=120) as client:
        response = client.post(endpoint, json=payload)

    if response.status_code >= 400:
        raise RuntimeError(f"Gemini API error: {response.status_code} {response.text}")

    data = response.json()
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected Gemini response: {data}") from exc

    # Normalize: strip markdown fences if present
    text = content.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Try to repair truncated JSON: find last complete object
        parsed = _repair_truncated_json(text)

    if not isinstance(parsed, list):
        raise RuntimeError("Gemini did not return a JSON array")
    return parsed


def _repair_truncated_json(text: str) -> list[dict[str, Any]]:
    """Attempt to recover products from truncated JSON output."""
    # Find the last complete "}" before truncation
    last_brace = text.rfind("}")
    if last_brace == -1:
        raise RuntimeError(f"Cannot repair JSON: no closing brace found")

    # Try progressively shorter substrings
    for end in range(last_brace + 1, max(last_brace - 500, 0), -1):
        candidate = text[:end]
        # Close the array
        candidate = candidate.rstrip().rstrip(",") + "\n]"
        try:
            result = json.loads(candidate)
            if isinstance(result, list):
                logger.info("Repaired truncated JSON: recovered %d items", len(result))
                return result
        except json.JSONDecodeError:
            continue

    raise RuntimeError("Cannot repair truncated JSON")


def deduplicate(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    no_id: list[dict[str, Any]] = []
    for p in products:
        art_nr = p.get("artikel_nr")
        if not art_nr:
            no_id.append(p)
            continue
        if art_nr not in seen:
            seen[art_nr] = p
    return list(seen.values()) + no_id


def _to_float(val: Any) -> float | None:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        cleaned = val.replace(",", ".").replace(" ", "").replace("€", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _to_int(val: Any) -> int | None:
    if val is None:
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(val)
    if isinstance(val, str):
        cleaned = val.replace(".", "").replace(",", "").replace(" ", "").replace("mm", "")
        try:
            return int(cleaned)
        except ValueError:
            return None
    return None


def _guess_norm(raw: dict[str, Any]) -> str | None:
    norm = raw.get("norm")
    if norm:
        return norm
    # Infer from system family and category
    system = (raw.get("system_familie") or "").lower()
    werkstoff = (raw.get("werkstoff") or "").lower()
    kategorie = (raw.get("kategorie") or "").lower()
    medium = (raw.get("medium") or "").lower()
    if "kg" in system and "pvc" in werkstoff:
        return "DIN EN 1401"
    if "acaro" in system or ("pp" in werkstoff and "rohr" in kategorie):
        return "DIN EN 13476-2"
    if "tegra" in system:
        return "DIN EN 13598-2"
    if "green connect" in system:
        return "DIN EN 13476-3"
    # Druckrohre norms
    if "pe" in werkstoff and ("wasser" in kategorie or "trinkwasser" in medium):
        return "DIN EN 12201-2"
    if "pe" in werkstoff and ("gas" in kategorie or "gas" in medium):
        return "DIN EN 1555-2"
    if "pvc" in werkstoff and ("wasser" in kategorie or "druck" in kategorie):
        return "DIN EN ISO 1452"
    return None


def build_product(raw: dict[str, Any], idx: int) -> Product | None:
    art_nr = raw.get("artikel_nr")
    if not art_nr:
        return None

    art_nr = str(art_nr).strip()
    artikelname = raw.get("artikelname", "")
    if not artikelname:
        return None

    # Determine price — prefer per-piece, fall back to per-meter
    preis = _to_float(raw.get("preis_eur_stk"))
    preiseinheit = "Stk"
    if preis is None:
        preis = _to_float(raw.get("preis_eur_m"))
        if preis is not None:
            preiseinheit = "m"

    # Build compatible DN string for fittings
    dn_anschluss = _to_int(raw.get("dn_anschluss"))
    dn_main = _to_int(raw.get("nennweite_dn"))
    kompatible_dn = None
    if dn_anschluss and dn_main and dn_anschluss != dn_main:
        kompatible_dn = f"{dn_main},{dn_anschluss}"
    elif dn_main:
        kompatible_dn = str(dn_main)

    # Build enriched description with SDR/PN/medium info
    beschreibung = raw.get("artikelbeschreibung") or ""
    sdr = raw.get("sdr")
    druckstufe = raw.get("druckstufe")
    medium = raw.get("medium")
    lieferform = raw.get("lieferform")
    if sdr and sdr not in beschreibung:
        beschreibung += f" {sdr}"
    if druckstufe and druckstufe not in beschreibung:
        beschreibung += f" {druckstufe}"
    if medium and medium not in beschreibung:
        beschreibung += f" {medium}"
    if lieferform and lieferform not in beschreibung:
        beschreibung += f" {lieferform}"

    # For PE pressure pipes, also store OD as part of DN description
    od = _to_int(raw.get("nennweite_od"))
    einsatzbereich = medium

    return Product(
        artikel_id=f"WAV-{art_nr}",
        hersteller="Wavin GmbH",
        hersteller_artikelnr=art_nr,
        artikelname=artikelname,
        artikelbeschreibung=beschreibung.strip() or None,
        kategorie=raw.get("kategorie"),
        unterkategorie=raw.get("unterkategorie"),
        werkstoff=raw.get("werkstoff"),
        nennweite_dn=dn_main,
        nennweite_od=od,
        laenge_mm=_to_int(raw.get("laenge_mm")),
        hoehe_mm=_to_int(raw.get("hoehe_mm")),
        wandstaerke_mm=_to_float(raw.get("wandstaerke_mm")),
        gewicht_kg=_to_float(raw.get("gewicht_kg")),
        belastungsklasse=raw.get("belastungsklasse"),
        steifigkeitsklasse_sn=raw.get("steifigkeitsklasse"),
        norm_primaer=_guess_norm(raw),
        system_familie=raw.get("system_familie"),
        kompatible_dn_anschluss=kompatible_dn,
        einsatzbereich=einsatzbereich,
        vk_listenpreis_netto=preis,
        waehrung="EUR",
        preiseinheit=preiseinheit,
        # Simulate reasonable stock and delivery for demo
        lager_gesamt=50,
        lager_rheinbach=30,
        lager_duesseldorf=20,
        lieferant_1_lieferzeit_tage=3,
        status="aktiv",
    )


def _process_pdf(pdf_path: str) -> list[dict[str, Any]]:
    """Extract products from a single Wavin PDF."""
    logger.info("=" * 60)
    logger.info("Processing: %s", Path(pdf_path).name)
    logger.info("=" * 60)

    pages = extract_pages(pdf_path)
    logger.info("Extracted %d pages with text", len(pages))

    # Skip cover pages, ToC, image-only pages (first ~5 pages)
    # and appendix pages (last ~10 pages)
    content_pages = pages[5:-10] if len(pages) > 20 else pages
    logger.info("Processing %d content pages (skipping cover/appendix)", len(content_pages))

    batches = create_batches(content_pages)
    logger.info("Created %d batches", len(batches))

    all_raw: list[dict[str, Any]] = []
    for batch_idx, (page_offset, batch_pages) in enumerate(batches):
        try:
            result = call_gemini(batch_pages, page_offset + 5)  # +5 for skipped pages
            all_raw.extend(result)
            logger.info(
                "Batch %d/%d (pages %d-%d): %d products found",
                batch_idx + 1, len(batches),
                page_offset + 6, page_offset + 5 + len(batch_pages),
                len(result),
            )
        except Exception as exc:
            logger.warning("Batch %d failed: %s", batch_idx + 1, exc)

    logger.info("Raw products from %s: %d", Path(pdf_path).name, len(all_raw))
    return all_raw


def main():
    # Collect PDF paths from arguments or auto-discover
    pdf_paths: list[str] = []
    if len(sys.argv) > 1:
        pdf_paths = sys.argv[1:]
    else:
        project_root = Path(__file__).resolve().parents[2]
        candidates = sorted(project_root.glob("Wavin*.pdf"))
        pdf_paths = [str(p) for p in candidates]

    if not pdf_paths:
        logger.error("No Wavin PDFs found. Pass paths as arguments or place in project root.")
        sys.exit(1)

    logger.info("Found %d Wavin PDF(s) to process:", len(pdf_paths))
    for p in pdf_paths:
        logger.info("  - %s", Path(p).name)

    # Process all PDFs
    all_raw: list[dict[str, Any]] = []
    for pdf_path in pdf_paths:
        raw = _process_pdf(pdf_path)
        all_raw.extend(raw)

    logger.info("Total raw products from all PDFs: %d", len(all_raw))

    deduped = deduplicate(all_raw)
    logger.info("After deduplication: %d products", len(deduped))

    # Build Product objects
    products: list[Product] = []
    for idx, raw in enumerate(deduped):
        product = build_product(raw, idx)
        if product:
            products.append(product)

    logger.info("Valid products to import: %d", len(products))

    if not products:
        logger.error("No products to import!")
        sys.exit(1)

    # Save raw extraction results for debugging
    debug_path = Path(__file__).parent / "wavin_extracted.json"
    with open(debug_path, "w") as f:
        json.dump(deduped, f, indent=2, ensure_ascii=False)
    logger.info("Raw extraction saved to %s", debug_path)

    # Import into database
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Remove old Wavin products
        deleted = db.query(Product).filter(Product.hersteller == "Wavin GmbH").delete()
        logger.info("Removed %d existing Wavin products", deleted)

        # Also remove old test data
        deleted_test = db.query(Product).filter(Product.artikel_id.like("ART-%")).delete()
        if deleted_test:
            logger.info("Removed %d old test products", deleted_test)

        db.add_all(products)
        db.commit()
        logger.info("Successfully imported %d Wavin products!", len(products))

        # Print summary by category
        from sqlalchemy import func
        summary = (
            db.query(Product.kategorie, func.count())
            .filter(Product.hersteller == "Wavin GmbH")
            .group_by(Product.kategorie)
            .all()
        )
        logger.info("--- Import Summary ---")
        for cat, count in sorted(summary, key=lambda x: x[1], reverse=True):
            logger.info("  %s: %d products", cat or "Unbekannt", count)
    finally:
        db.close()


if __name__ == "__main__":
    main()
