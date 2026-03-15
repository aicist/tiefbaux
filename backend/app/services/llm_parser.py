"""LLM-first LV parsing: Gemini extracts positions, quantities, classification and parameters in one pass."""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

import httpx
import pdfplumber

from ..config import settings
from ..schemas import LVPosition, ProjectMetadata, TechnicalParameters
from .ai_interpreter import InterpretationError, _infer_with_heuristics, _normalize_json_array

logger = logging.getLogger(__name__)

PAGE_BATCH_SIZE = 8
PAGE_OVERLAP = 1

SYSTEM_INSTRUCTION = (
    "Du bist ein erfahrener Tiefbau-Fachberater bei einem Baustoffhaendler. "
    "Du analysierst Leistungsverzeichnisse (LV) aus Bauausschreibungen.\n\n"
    "Deine Aufgabe:\n"
    "1. Finde ALLE bepreisbaren Positionen im Text. Eine Position hat eine Ordnungszahl "
    "(z.B. '1.5.3'), eine Beschreibung, eine Menge und eine Einheit.\n"
    "2. Klassifiziere jede Position als 'material' oder 'dienstleistung'.\n"
    "3. Extrahiere technische Parameter fuer Material-Positionen.\n\n"
    "Regeln fuer die Klassifikation:\n"
    "- 'material': Positionen die ein physisches Produkt erfordern das geliefert werden muss "
    "(Rohre, Schachtteile, Abdeckungen, Formstücke, Rinnen, Dichtungen, Geotextilien, Vlies, "
    "Kies, Sand zum Einbau etc.)\n"
    "- 'dienstleistung': Reine Arbeitsleistungen OHNE Materialbedarf aus dem Baustoffhandel: "
    "Abbruch, Demontage, Rueckbau, Erdarbeiten (Aushub, Grabenaushub, Grabentiefe, "
    "Verfuellung, Verdichtung, Planum, Boden loesen, Boden einbauen, Bodenabfuhr), "
    "Transport, Entsorgung, Baustelleneinrichtung, Vermessung, Verkehrssicherung, "
    "Wasserhaltung, Stundenlohnarbeiten, Vorhaltung, Sperrung, Druckprobe, Absicherung, "
    "Roden, Aufnehmen und Entsorgen von Bestandsmaterial (Pflaster, Asphalt, Bordsteine, "
    "Zaeune, Tore, Leuchten etc.), Ausbauen bestehender Leitungen/Schaechte, "
    "Oberflaeche wiederherstellen, Asphalt einbauen, Pflaster verlegen (ohne Materiallieferung)\n"
    "- WICHTIG: 'aufnehmen und entsorgen', 'ausbauen und entsorgen', 'abbrechen', 'demontieren', "
    "'rueckbauen', 'roden', 'entfernen' = IMMER 'dienstleistung', auch wenn technische Begriffe "
    "wie DN oder Schacht vorkommen!\n"
    "- Wenn eine Position Material UND Einbauarbeit beschreibt (z.B. 'KG-Rohr DN150 liefern und "
    "verlegen'), klassifiziere als 'material'.\n"
    "- WICHTIG: Beachte den Gewerk-Kontext anhand der Ordnungszahl-Praefix:\n"
    "  OZ 25.xxx = Gasversorgung → Rohre sind 'Gasrohre' (nicht Kanalrohre!)\n"
    "  OZ 30.xxx = Wasserversorgung → Rohre sind 'Wasserrohre' (nicht Kanalrohre!)\n"
    "  OZ 35.xxx = Kabelschutz → Rohre sind 'Kabelschutz' (nicht Kanalrohre!)\n"
    "  OZ 01.xxx oder ohne klaren Gewerk-Praefix = Kanalrohre/Entwaesserung\n"
    "- WICHTIG: Wenn das Material vom Auftraggeber gestellt/beigestellt wird "
    "(z.B. 'wird durch den AG ... gestellt', 'ab Lager des AG', 'beigestellt'), "
    "ist es 'dienstleistung' - der Auftragnehmer liefert kein Material!\n"
    "- Verbindungsleitungen in der Hausinstallation (inkl. Fittings/Befestigungen) "
    "sind 'material', da der Auftragnehmer Rohr und Fittings mitbringt - "
    "gilt fuer Gas UND Wasser gleichermassen.\n\n"
    "Erkenne alle gaengigen Einheiten: m, m2, m², m3, m³, Stk, Stck, St, Stueck, kg, to, t, "
    "h, Std, StD, lfm, lfdm, lfd.m, Psch, psch, Pausch, Wo, mWo, cbm, etc.\n\n"
    "Gib ein JSON-Array zurueck. Jedes Objekt hat diese Felder:\n"
    "- ordnungszahl: string (z.B. '1.5.3')\n"
    "- description: string (Beschreibung der Position mit allen technischen Details wie Norm, SN-Klasse, DN, Material, Belastungsklasse — max 200 Zeichen)\n"
    "- quantity: number | null\n"
    "- unit: string | null\n"
    "- position_type: 'material' | 'dienstleistung'\n"
    "- product_category: string | null (nur fuer material; verwende AUSSCHLIESSLICH "
    "einen dieser Werte oder null: Kanalrohre, Schachtabdeckungen, Schachtbauteile, "
    "Formstuecke, Strassenentwässerung, Rinnen, Dichtungen & Zubehoer, Geotextilien, "
    "Gasrohre, Wasserrohre, Druckrohre, Kabelschutz. "
    "Wenn keine Kategorie passt (z.B. Sand, Asphalt, Pflaster, Bordsteine, Oberboden), "
    "setze null!)\n"
    "- product_subcategory: string | null\n"
    "- material: string | null (PP, PVC-U, Stahlbeton, Beton, Gusseisen, HDPE, PE, PE 100, PE 100-RC, Steinzeug)\n"
    "- nominal_diameter_dn: integer | null\n"
    "- load_class: string | null (A15, B125, C250, D400, E600, F900)\n"
    "- norm: string | null (z.B. 'DIN EN 1401', 'DIN EN 13476', 'DIN EN 1916')\n"
    "- stiffness_class_sn: integer | null (Ringsteifigkeitsklasse, z.B. 4, 8, 16 bei SN4, SN8, SN16)\n"
    "- dimensions: string | null (Abmessungen wie '300/500', '500x500', '300x300mm' — "
    "insbesondere bei Aufsaetzen, Rosten, Rahmen, Rinnen. Uebernimm exakt die Angabe aus dem LV.)\n"
    "- reference_product: string | null\n"
    "- installation_area: string | null (Fahrbahn, Gehweg, Erdeinbau)\n"
    "- sortiment_relevant: boolean (true wenn ein Tiefbau-Baustoffhaendler dieses Produkt "
    "fuehren wuerde: Rohre, Schaechte, Formstücke, Abdeckungen, Rinnen, Dichtungen, "
    "Geotextilien, Druckrohre, Kabelschutzrohre. "
    "false fuer: Stuetzmauern, Bordsteine, Pflaster, Asphalt, Poller, Blockstufen, "
    "Sand/Kies/Schotter als reines Schuettgut, Hydrantenarmaturen, Zaeune, Beleuchtung, "
    "Rasensaat, Oberboden, Hausanschlussgarnituren. "
    "Bei Dienstleistungen: false)\n\n"
    "Fuer Dienstleistungs-Positionen setze alle technischen Parameter auf null.\n"
    "Ueberspringe Ueberschriften (z.B. '1.5 Entwaesserungsleitungen'), Vorbemerkungen, "
    "Hinweise und nicht-bepreisbare Zeilen (ohne Menge/Einheit).\n\n"
    "WICHTIG - Seitenumbrueche: Positionen koennen ueber Seitenumbrueche gehen. "
    "Wenn eine Seite mit 'Leistungsbeschreibung auf voranstehender Seite' oder "
    "aehnlichem Fortsetzungstext beginnt, gefolgt von einer Menge und Einheit, "
    "gehoert diese Menge zur letzten Position der vorherigen Seite. "
    "Die Menge/Einheit am ENDE einer Position (direkt vor der naechsten Positionsnummer "
    "oder vor 'Uebertrag') ist IMMER die korrekte Gesamtmenge der Position - "
    "NICHT einzelne Stueckzahlen aus der Komponentenliste innerhalb der Beschreibung!\n"
    "Gib NUR das JSON-Array zurueck, keine Erklaerung."
)


METADATA_INSTRUCTION = (
    "Du bist ein erfahrener Tiefbau-Fachberater. Analysiere die ersten Seiten dieses "
    "Leistungsverzeichnisses und extrahiere die Projekt-Metadaten.\n\n"
    "Gib ein JSON-Objekt zurueck mit diesen Feldern:\n"
    "- bauvorhaben: string | null (Bauvorhaben-Bezeichnung, Projekttitel)\n"
    "- objekt_nr: string | null (Objekt-/Projektnummer, Vergabenummer, Ausschreibungsnummer)\n"
    "- submission_date: string | null (Submissionsdatum/Angebotsfrist im Format TT.MM.JJJJ)\n"
    "- auftraggeber: string | null (Auftraggeber/Bauherr)\n"
    "- kunde_name: string | null (Name des Unternehmens das die Anfrage/Ausschreibung stellt)\n"
    "- kunde_adresse: string | null (Adresse des Absenders/Anfragenden)\n\n"
    "Gib NUR das JSON-Objekt zurueck, keine Erklaerung."
)


def _extract_metadata_with_llm(first_pages_text: str) -> ProjectMetadata:
    """Extract project metadata from the first pages of the LV using Gemini."""
    if not settings.gemini_api_key:
        return ProjectMetadata()

    payload = {
        "system_instruction": {"parts": [{"text": METADATA_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": first_pages_text}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(endpoint, json=payload)
        if response.status_code >= 400:
            logger.warning("Metadata extraction failed: %s", response.status_code)
            return ProjectMetadata()
        data = response.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        # Metadata is a JSON object, not an array — extract {...}
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.strip("`").replace("json", "", 1).strip()
        obj_start = stripped.find("{")
        obj_end = stripped.rfind("}")
        if obj_start == -1 or obj_end == -1 or obj_end <= obj_start:
            logger.warning("Metadata: no JSON object found in response")
            return ProjectMetadata()
        parsed = json.loads(stripped[obj_start : obj_end + 1])
        if isinstance(parsed, dict):
            return ProjectMetadata(**{k: v for k, v in parsed.items() if v})
    except Exception as exc:
        logger.warning("Metadata extraction error: %s", exc)
    return ProjectMetadata()


_CONTINUATION_PATTERNS = (
    "leistungsbeschreibung auf voranstehender seite",
    "leistungsbeschreibung auf vorhergehender seite",
    "fortsetzung von seite",
    "übertrag",
)


def extract_raw_text_pages(pdf_bytes: bytes) -> list[str]:
    """Extract raw text per page using pdfplumber.

    Detects page-continuation patterns (e.g. 'Leistungsbeschreibung auf
    voranstehender Seite') and appends the continuation text to the previous
    page so that positions spanning a page break are kept together.
    """
    raw_pages: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if text.strip():
                raw_pages.append(text)

    if not raw_pages:
        return raw_pages

    # Merge continuation pages into the previous page
    merged: list[str] = [raw_pages[0]]
    for page_text in raw_pages[1:]:
        lines = page_text.strip().split("\n")
        # Skip header lines (Architekt, Objekt, POS. LEISTUNGSBESCHREIBUNG etc.)
        content_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if any(pat in stripped for pat in _CONTINUATION_PATTERNS):
                content_start = i
                break
        if content_start > 0:
            # Found continuation — extract the continuation block (up to next position)
            continuation_lines = lines[content_start:]
            # Find where actual new positions start (line starting with a position number)
            import re
            merge_end = len(continuation_lines)
            for j, cline in enumerate(continuation_lines):
                # A new position starts with a number like "04.0016" at the beginning
                if j > 0 and re.match(r"^\s*\d{2}\.\d{4}\s", cline):
                    merge_end = j
                    break

            # Append continuation to previous page
            merged[-1] += "\n" + "\n".join(continuation_lines[:merge_end])
            # Rest of page (new positions) stays as a new page
            remaining = "\n".join(lines[:content_start]) + "\n" + "\n".join(continuation_lines[merge_end:])
            if remaining.strip():
                merged.append(remaining)
        else:
            merged.append(page_text)

    return merged


def _create_page_batches(pages: list[str]) -> list[tuple[int, list[str]]]:
    """Split pages into overlapping batches. Returns (page_offset, page_texts) tuples."""
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


def _build_batch_prompt(page_texts: list[str], page_offset: int) -> str:
    pages_block = ""
    for i, text in enumerate(page_texts):
        pages_block += f"\n--- Seite {page_offset + i + 1} ---\n{text}\n"
    return f"Analysiere den folgenden LV-Text und extrahiere alle bepreisbaren Positionen:\n{pages_block}"


def _call_gemini_parse_batch(page_texts: list[str], page_offset: int) -> list[dict[str, Any]]:
    """Call Gemini to parse a batch of PDF pages into structured positions."""
    if not settings.gemini_api_key:
        raise InterpretationError("GEMINI_API_KEY not configured")

    prompt = _build_batch_prompt(page_texts, page_offset)

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )

    with httpx.Client(timeout=90) as client:
        response = client.post(endpoint, json=payload)

    if response.status_code >= 400:
        raise InterpretationError(f"Gemini API error: {response.status_code} {response.text}")

    data = response.json()
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise InterpretationError(f"Unexpected Gemini response format: {data}") from exc

    normalized = _normalize_json_array(content)

    try:
        parsed: list[dict[str, Any]] = json.loads(normalized)
    except json.JSONDecodeError as exc:
        raise InterpretationError(f"Invalid JSON returned by model: {exc}") from exc

    if not isinstance(parsed, list):
        raise InterpretationError("Gemini did not return a JSON array")

    return parsed


def _assign_source_pages(
    batch_result: list[dict[str, Any]], page_offset: int, num_pages: int,
) -> list[dict[str, Any]]:
    """Tag each raw position dict with a source_page based on the batch page offset."""
    # Simple heuristic: assign page_offset+1 (1-based) to all positions in this batch.
    # Better than nothing — positions are roughly ordered by page.
    mid_page = page_offset + (num_pages // 2) + 1
    for pos in batch_result:
        if "source_page" not in pos:
            pos["source_page"] = mid_page
    return batch_result


def _deduplicate_positions(all_raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the most complete occurrence of each ordnungszahl.

    When a position spans a page boundary, different batches may parse it
    with varying completeness. Prefer the entry that has quantity filled in,
    and merge missing fields from duplicates.
    """
    seen: dict[str, dict[str, Any]] = {}
    for pos in all_raw:
        oz = pos.get("ordnungszahl", "")
        if not oz:
            continue
        if oz not in seen:
            seen[oz] = pos
        else:
            existing = seen[oz]
            # Prefer the entry with a quantity if one is missing
            if existing.get("quantity") is None and pos.get("quantity") is not None:
                # New entry has quantity, old doesn't — use new as base
                for key, val in existing.items():
                    if val is not None and pos.get(key) is None:
                        pos[key] = val
                seen[oz] = pos
            else:
                # Fill missing fields from the duplicate
                for key, val in pos.items():
                    if val is not None and existing.get(key) is None:
                        existing[key] = val
    return list(seen.values())


def _to_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", ".").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _assemble_position(idx: int, raw: dict[str, Any]) -> LVPosition:
    """Convert a raw LLM dict into an LVPosition."""
    pos_type = raw.get("position_type", "material")
    if pos_type not in ("material", "dienstleistung"):
        pos_type = "material"

    quantity = _to_float(raw.get("quantity"))
    unit = raw.get("unit")
    description = raw.get("description", "")

    params = TechnicalParameters(
        product_category=raw.get("product_category"),
        product_subcategory=raw.get("product_subcategory"),
        material=raw.get("material"),
        nominal_diameter_dn=raw.get("nominal_diameter_dn"),
        load_class=raw.get("load_class"),
        norm=raw.get("norm"),
        dimensions=raw.get("dimensions"),
        color=raw.get("color"),
        quantity=quantity,
        unit=unit,
        reference_product=raw.get("reference_product"),
        installation_area=raw.get("installation_area"),
        stiffness_class_sn=raw.get("stiffness_class_sn"),
        sortiment_relevant=raw.get("sortiment_relevant"),
    )

    return LVPosition(
        id=f"pos-{idx}",
        ordnungszahl=raw.get("ordnungszahl", f"?.{idx}"),
        description=description,
        raw_text=description,
        quantity=quantity,
        unit=unit,
        billable=pos_type == "material",
        position_type=pos_type,
        parameters=params,
        source_page=raw.get("source_page"),
    )


_VALID_CATEGORIES = {
    "kanalrohre", "schachtabdeckungen", "schachtbauteile", "formstuecke",
    "formstücke", "strassenentwässerung", "strassenentwaesserung", "rinnen",
    "dichtungen & zubehoer", "dichtungen & zubehör", "geotextilien",
    "gasrohre", "wasserrohre", "druckrohre", "kabelschutz",
}

_CLIENT_PROVIDED_RE = re.compile(
    r"(?:wird\s+(?:durch|vom)\s+(?:den\s+)?AG\b.*?gestellt"
    r"|ab\s+Lager\s+(?:des\s+)?AG\b"
    r"|beigestellt"
    r"|vom\s+AG\s+bereitgestellt"
    r"|AG\s+ab\s+Lager\b.*?gestellt)",
    re.IGNORECASE,
)


def _validate_with_heuristics(positions: list[LVPosition]) -> list[LVPosition]:
    """Run heuristic enrichment to fill gaps the LLM might have left."""
    validated: list[LVPosition] = []
    for pos in positions:
        # Fix: reclassify material→DL if material is provided by client (AG)
        if pos.position_type == "material" and _CLIENT_PROVIDED_RE.search(pos.description or ""):
            logger.info(
                "Reclassifying %s '%s' from material→dienstleistung (material provided by client)",
                pos.ordnungszahl, pos.description[:60],
            )
            pos = pos.model_copy(update={
                "position_type": "dienstleistung",
                "billable": False,
                "parameters": TechnicalParameters(
                    product_category=None, product_subcategory=None,
                    material=None, nominal_diameter_dn=None,
                    load_class=None, norm=None, dimensions=None,
                    color=None, quantity=pos.quantity, unit=pos.unit,
                    reference_product=None, installation_area=None,
                ),
            })

        if pos.position_type == "dienstleistung":
            validated.append(pos)
            continue

        # Sanitize invalid categories
        cat = pos.parameters.product_category
        if cat and cat.lower() not in _VALID_CATEGORIES:
            logger.info(
                "Stripping invalid category '%s' from %s '%s'",
                cat, pos.ordnungszahl, pos.description[:60],
            )
            pos = pos.model_copy(update={
                "parameters": pos.parameters.model_copy(update={"product_category": None}),
            })

        heuristic_params = _infer_with_heuristics(pos)
        merged = pos.parameters.model_dump()
        # Only fill in nulls from heuristics, don't override LLM values
        for key, value in heuristic_params.model_dump().items():
            if merged.get(key) is None and value is not None:
                merged[key] = value
        validated.append(pos.model_copy(update={"parameters": TechnicalParameters(**merged)}))
    return validated


def parse_lv_with_llm(pdf_bytes: bytes) -> tuple[list[LVPosition], ProjectMetadata]:
    """Parse an LV PDF using Gemini LLM for position extraction and classification.

    Returns (positions, metadata) tuple.
    """
    pages = extract_raw_text_pages(pdf_bytes)
    if not pages:
        return [], ProjectMetadata()

    # Extract metadata from first few pages (in parallel with position parsing)
    first_pages_text = "\n".join(pages[:3])
    metadata = _extract_metadata_with_llm(first_pages_text)

    batches = _create_page_batches(pages)
    all_raw_positions: list[dict[str, Any]] = []

    for page_offset, batch_pages in batches:
        try:
            batch_result = _call_gemini_parse_batch(batch_pages, page_offset)
            _assign_source_pages(batch_result, page_offset, len(batch_pages))
            all_raw_positions.extend(batch_result)
            logger.info(
                "LLM batch pages %d-%d: %d positions found",
                page_offset + 1,
                page_offset + len(batch_pages),
                len(batch_result),
            )
        except InterpretationError as exc:
            logger.warning("LLM batch at page %d failed: %s", page_offset + 1, exc)

    if not all_raw_positions:
        raise InterpretationError("LLM returned no positions from any batch")

    deduped = _deduplicate_positions(all_raw_positions)

    # Sort by ordnungszahl
    def _sort_key(raw: dict[str, Any]) -> list[int]:
        oz = raw.get("ordnungszahl", "0")
        try:
            return [int(x) for x in oz.split(".")]
        except ValueError:
            return [999]

    deduped.sort(key=_sort_key)

    positions = [_assemble_position(idx, raw) for idx, raw in enumerate(deduped, start=1)]

    # Validate with heuristics to fill gaps
    positions = _validate_with_heuristics(positions)

    logger.info(
        "LLM parsing complete: %d positions (%d material, %d dienstleistung)",
        len(positions),
        sum(1 for p in positions if p.position_type == "material"),
        sum(1 for p in positions if p.position_type == "dienstleistung"),
    )

    return positions, metadata
