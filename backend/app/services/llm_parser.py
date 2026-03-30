"""LLM-first LV parsing: Gemini extracts positions, quantities, classification and parameters in one pass."""

from __future__ import annotations

import io
import json
import logging
import re
import time
from typing import Any

import httpx
import pdfplumber
from pypdf import PdfReader

from ..config import settings
from ..schemas import LVPosition, ProjectMetadata, TechnicalParameters
from .ai_interpreter import InterpretationError, _infer_with_heuristics, _maybe_reclassify_as_material, _normalize_json_array, _post_merge_sanity

logger = logging.getLogger(__name__)

PAGE_BATCH_SIZE = 8
PAGE_OVERLAP = 1


def _gemini_models() -> list[str]:
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    deduped: list[str] = []
    for model in models:
        normalized = (model or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _should_retry_gemini(status_code: int | None, exc: Exception | None = None) -> bool:
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError))
    return status_code in {408, 425, 429, 500, 502, 503, 504}


def _post_gemini(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for model in _gemini_models():
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={settings.gemini_api_key}"
        )
        for attempt in range(settings.gemini_retry_attempts):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(endpoint, json=payload)
                if response.status_code >= 400:
                    message = f"Gemini API error ({model}): {response.status_code} {response.text}"
                    if attempt + 1 < settings.gemini_retry_attempts and _should_retry_gemini(response.status_code):
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    last_error = InterpretationError(message)
                    break
                return response.json()
            except Exception as exc:
                if attempt + 1 < settings.gemini_retry_attempts and _should_retry_gemini(None, exc):
                    time.sleep(0.6 * (attempt + 1))
                    continue
                last_error = InterpretationError(f"Gemini request failed ({model}): {exc}")
                break
    if last_error is None:
        last_error = InterpretationError("Gemini request failed without response")
    raise last_error

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
    "Wenn keine Kategorie passt (z.B. Sand, Asphalt, Pflaster, Pflasterrinne, Bordsteine, Oberboden, Bitumenfugenband), "
    "setze null! WICHTIG: 'Pflasterrinne' ist KEINE Entwässerungsrinne sondern verlegte Pflastersteine — Kategorie null!)\n"
    "- product_subcategory: string | null\n"
    "- material: string | null (PP, PVC-U, Stahlbeton, Beton, Polymerbeton, Gusseisen, HDPE, PE, PE 100, PE 100-RC, Steinzeug)\n"
    "- nominal_diameter_dn: integer | null (Bei Schaechten: 'Lichter Schachtdurchmesser' verwenden, NICHT den Zulauf-/Ablauf-DN! DN1.000 = 1000)\n"
    "- secondary_nominal_diameter_dn: integer | null (zweite Nennweite bei Formstücken/Anschlüssen/Reduktionen, z.B. DN 200/160 -> 160, bei 'Anschluss 110 mm' -> 110)\n"
    "- load_class: string | null (A15, B125, C250, D400, E600, F900)\n"
    "- norm: string | null (z.B. 'DIN EN 1401', 'DIN EN 13476', 'DIN EN 1916')\n"
    "- stiffness_class_sn: integer | null (Ringsteifigkeitsklasse, z.B. 4, 8, 16 bei SN4, SN8, SN16)\n"
    "- dimensions: string | null (Abmessungen wie '300/500', '500x500', '300x300mm' — "
    "insbesondere bei Aufsaetzen, Rosten, Rahmen, Rinnen. Uebernimm exakt die Angabe aus dem LV.)\n"
    "- reference_product: string | null\n"
    "- installation_area: string | null (Fahrbahn, Gehweg, Erdeinbau)\n"
    "- system_family: string | null (Produkt-/Systemfamilie wie KG PVC-U, Wavin Tegra, AWADUKT HPP, Wavin X-Stream, KG 2000)\n"
    "- connection_type: string | null (Steckmuffe, Spitzende, Flansch, Muffe, Doppelmuffe, Klemmverbindung)\n"
    "- seal_type: string | null (Lippendichtung, Gleitringdichtung, Profildichtung, Doppeldichtung)\n"
    "- compatible_systems: string[] | null (Systeme/Anschlusswelten die explizit genannt werden, z.B. ['KG','HT'] oder ['PVC-KG','PE-HD'])\n"
    "- sortiment_relevant: boolean (true wenn ein Tiefbau-Baustoffhaendler dieses Produkt "
    "fuehren wuerde: Rohre, Schaechte, Formstücke, Abdeckungen, Rinnen, Dichtungen, "
    "Geotextilien, Druckrohre, Kabelschutzrohre. "
    "false fuer: Stuetzmauern, Bordsteine, Pflaster, Pflasterrinne, Asphalt, Poller, Blockstufen, "
    "Sand/Kies/Schotter als reines Schuettgut, Hydrantenarmaturen, Zaeune, Beleuchtung, "
    "Rasensaat, Oberboden, Hausanschlussgarnituren, Bitumenfugenband, Mauerscheiben, Trennlagen/Folien. "
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
    "- bauvorhaben: string | null (Bauvorhaben-Bezeichnung, Projekttitel. "
    "Suche in Kopfzeilen wie 'Projekt: ...', 'Bauvorhaben: ...', 'Objekt: ...' "
    "oder im Titel/Betreff des Dokuments)\n"
    "- objekt_nr: string | null (Objekt-/Projektnummer, Vergabenummer, Ausschreibungsnummer. "
    "Kann auch in der Kopfzeile stehen, z.B. 'Projekt 23-18 - ...' → objekt_nr='23-18')\n"
    "- submission_date: string | null (Submissionsdatum/Angebotsfrist im Format TT.MM.JJJJ. "
    "Falls nur ein Druckdatum vorhanden ist, nutze dieses als Anhaltspunkt)\n"
    "- auftraggeber: string | null (Name der auftraggebenden Organisation/Firma/Behörde/Kommune, NICHT der persönliche Name des Bauherrn)\n"
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
    try:
        data = _post_gemini(payload, timeout=30)
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
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    raw_pages.append(text)
    except Exception as exc:
        logger.warning("pdfplumber raw text extraction failed, falling back to pypdf: %s", exc)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
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

    data = _post_gemini(payload, timeout=90)
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


def _to_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    if isinstance(value, str):
        items = [piece.strip() for piece in re.split(r"[,;/]", value) if piece.strip()]
        return items or None
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
        secondary_nominal_diameter_dn=raw.get("secondary_nominal_diameter_dn"),
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
        system_family=raw.get("system_family"),
        connection_type=raw.get("connection_type"),
        seal_type=raw.get("seal_type"),
        compatible_systems=_to_string_list(raw.get("compatible_systems")),
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

_REFERENCE_TO_PREVIOUS_RE = re.compile(
    r"^\s*(wie\s+zuvor|wie\s+position|wie\s+vorstehend|wie\s+vorhergehend)",
    re.IGNORECASE,
)

_STRUCTURAL_PARAM_FIELDS = (
    "product_category",
    "product_subcategory",
    "material",
    "nominal_diameter_dn",
    "secondary_nominal_diameter_dn",
    "load_class",
    "norm",
    "dimensions",
    "reference_product",
    "installation_area",
    "stiffness_class_sn",
    "system_family",
    "connection_type",
    "seal_type",
    "compatible_systems",
    "components",
)


def _is_reference_position(position: LVPosition) -> bool:
    text = f"{position.description}\n{position.raw_text}".strip()
    return bool(_REFERENCE_TO_PREVIOUS_RE.match(text))


def _inherit_reference_context(positions: list[LVPosition]) -> list[LVPosition]:
    inherited: list[LVPosition] = []
    previous_material: LVPosition | None = None

    for position in positions:
        current = position
        if current.position_type == "material" and _is_reference_position(current) and previous_material:
            merged = current.parameters.model_dump()
            base = previous_material.parameters.model_dump()
            inferred_base = _infer_with_heuristics(previous_material).model_dump()
            # Detect if the current position has a different material than the base
            cur_mat = (merged.get("material") or "").lower()
            base_mat = (base.get("material") or inferred_base.get("material") or "").lower()
            material_changed = cur_mat and base_mat and cur_mat != base_mat
            # Fields that should NOT be inherited across material boundaries
            _MATERIAL_BOUND_FIELDS = {"stiffness_class_sn", "norm", "system_family", "connection_type", "seal_type", "compatible_systems"}
            # For "wie zuvor" positions, category/subcategory from base take priority
            # because the LLM often misclassifies these minimal-text positions.
            # Prefer heuristic values for these fields since heuristics are grounded in text keywords.
            _INHERIT_OVERRIDE_FIELDS = {"product_category", "product_subcategory"}
            for field in _STRUCTURAL_PARAM_FIELDS:
                base_value = base.get(field)
                if field == "components":
                    inferred_components = inferred_base.get(field) or []
                    base_components = base_value or []
                    if len(inferred_components) > len(base_components):
                        base_value = inferred_components
                if base_value in (None, "", []) or (field in _INHERIT_OVERRIDE_FIELDS and inferred_base.get(field)):
                    inferred_val = inferred_base.get(field)
                    if inferred_val not in (None, "", []):
                        base_value = inferred_val
                # Don't inherit SN/norm/system across material changes
                if material_changed and field in _MATERIAL_BOUND_FIELDS:
                    continue
                if base_value not in (None, "", []):
                    if merged.get(field) in (None, "", []) or field in _INHERIT_OVERRIDE_FIELDS:
                        merged[field] = base_value
            current = current.model_copy(update={"parameters": TechnicalParameters(**merged)})

        inherited.append(current)
        if current.position_type == "material":
            previous_material = current

    return inherited


def _merge_heuristic_parameters(position: LVPosition, heuristic_params: TechnicalParameters) -> TechnicalParameters:
    merged = position.parameters.model_dump()
    is_reference = _is_reference_position(position)
    category_conflict = (
        heuristic_params.product_category
        and merged.get("product_category")
        and heuristic_params.product_category != merged.get("product_category")
    )
    subcategory_conflict = (
        heuristic_params.product_subcategory
        and merged.get("product_subcategory")
        and heuristic_params.product_subcategory != merged.get("product_subcategory")
    )

    if is_reference or category_conflict or subcategory_conflict:
        for field in _STRUCTURAL_PARAM_FIELDS:
            value = getattr(heuristic_params, field)
            if field == "components" and merged.get("components") and value:
                inherited_components = merged.get("components") or []
                seen_keys = {
                    (
                        comp.get("component_name"),
                    )
                    for comp in inherited_components
                }
                merged_components = list(inherited_components)
                for comp in value:
                    key = (comp.component_name,)
                    if key not in seen_keys:
                        merged_components.append(comp)
                        seen_keys.add(key)
                merged[field] = merged_components
                continue
            if value not in (None, "", []):
                merged[field] = value
    else:
        for key, value in heuristic_params.model_dump().items():
            if merged.get(key) is None and value not in (None, "", []):
                merged[key] = value

    return TechnicalParameters(**merged)


def _is_service_by_heuristic(pos: LVPosition) -> bool:
    """Check if a position classified as 'material' by LLM is actually a service/labor position."""
    text = f"{pos.description}\n{pos.raw_text}".lower()

    # Positions with DN or load class have a strong product signal — don't reclassify
    from .ai_interpreter import DN_RE, LOAD_CLASSES
    if DN_RE.search(pos.raw_text or ""):
        return False
    if any(lc.lower() in text for lc in LOAD_CLASSES):
        return False

    # "Zulage" = price surcharge for labor, not a standalone product
    if re.match(r"^\s*zulage\b", text):
        return True

    # Service keywords that override material classification
    _SERVICE_OVERRIDE_KEYWORDS = (
        "kopfloch", "anschlussarbeiten",
        "schnittkanten", "schnitt ausklinkung",
        "plattendruckversuch", "lastplattendruck", "druckversuch",
        "regulieren", "höhenanpass", "hoehen",
        "tragschicht", "überarbeiten", "ueberarbeiten",
    )
    if any(kw in text for kw in _SERVICE_OVERRIDE_KEYWORDS):
        return True

    return False


def _validate_with_heuristics(positions: list[LVPosition]) -> list[LVPosition]:
    """Run heuristic enrichment to fill gaps the LLM might have left."""
    positions = _inherit_reference_context(positions)
    validated: list[LVPosition] = []
    for pos in positions:
        # Fix: reclassify material→DL if material is provided by client (AG)
        # or if the position is clearly a service/labor position
        _reclassify_as_dl = False
        if pos.position_type == "material":
            if _CLIENT_PROVIDED_RE.search(pos.description or ""):
                logger.info("Reclassifying %s→DL (material provided by client)", pos.ordnungszahl)
                _reclassify_as_dl = True
            elif _is_service_by_heuristic(pos):
                logger.info("Reclassifying %s→DL (service keywords detected)", pos.ordnungszahl)
                _reclassify_as_dl = True

        if _reclassify_as_dl:
            pos = pos.model_copy(update={
                "position_type": "dienstleistung",
                "billable": False,
                "parameters": TechnicalParameters(
                    product_category=None, product_subcategory=None,
                    material=None, nominal_diameter_dn=None,
                    secondary_nominal_diameter_dn=None,
                    load_class=None, norm=None, dimensions=None,
                    color=None, quantity=pos.quantity, unit=pos.unit,
                    reference_product=None, installation_area=None,
                    system_family=None, connection_type=None,
                    seal_type=None, compatible_systems=None,
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
        merged_params = _merge_heuristic_parameters(pos, heuristic_params)
        pos = _maybe_reclassify_as_material(pos)
        merged_params = _post_merge_sanity(merged_params, pos)
        validated.append(pos.model_copy(update={"parameters": merged_params}))
    return validated


_OZ_LINE_RE = re.compile(r"^\s*(\d+[\d.]*\d)\s")


def _map_oz_to_page(pdf_bytes: bytes, ordnungszahlen: list[str]) -> dict[str, int]:
    """Find the actual 1-based PDF page number for each ordnungszahl."""
    result: dict[str, int] = {}
    wanted = set(ordnungszahlen)
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            for line in text.split("\n"):
                m = _OZ_LINE_RE.match(line)
                if m and "." in m.group(1):
                    oz = m.group(1)
                    if oz in wanted and oz not in result:
                        result[oz] = page_num
    return result
_SKIP_LINE_RE = re.compile(
    r"^\s*(Architekt|Objekt\s*:|Bauherr|Seite\s+\d|LEISTUNGSVERZEICHNIS|"
    r"Leistungsbeschreibung auf vo|POS\.\s|---|"
    r"[Üü]bertrag:?\s*$|Bauvorhaben:\s*\d|Projekt-Nr\.|Ausschr\.-Nr\.|"
    r"Pos-Nr\.\s+Menge\s+ME|EP\s*/\s*EUR|GP\s*/\s*EUR|Datum:\s*\d)",
    re.IGNORECASE,
)

_DESCRIPTION_METADATA_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\.?\s*stl\s*[-.]?\s*nr\b|"
    r"l\s*eistungsbereich\s*:|"
    r"projekt:|"
    r"lv:|"
    r"angebotsaufforderung\b|"
    r"ordnungszahl\s+leistungsbeschreibung\b|"
    r"menge\s+me\b|"
    r"einheitspreis\b|"
    r"gesamtbetrag\b|"
    r"in\s+eur\b|"
    r"seite\s*:?\s*\d+\b|"
    r"[üu]bertrag:?\b"
    r")",
    re.IGNORECASE,
)


def _derive_description_from_raw_text(raw_text: str, fallback: str | None = None) -> str:
    """Build a stable short description directly from the original LV block.

    This avoids shifted LLM summaries when the model assigns the next position's
    header to the current OZ. Keep the first meaningful 1-2 lines and prefer the
    more complete variant when the first line is only a truncated duplicate.
    """
    if not raw_text:
        return fallback or ""

    candidates: list[str] = []
    quantity_line_re = re.compile(
        r"^\s*[\d.,]+\s+(Stück|Stck|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b",
        re.IGNORECASE,
    )
    technical_line_re = re.compile(
        r"(dn\s*\d+|sn\s*\d+|din|d[0-9]{3}|[0-9]+\s*(mm|cm|m)\b|"
        r"[0-9]+\s*/\s*[0-9]+|[0-9]+\s*x\s*[0-9]+|"
        r"beton|stahlbeton|pp\b|pvc|pe\b|pe-?hd|steinzeug|polymerbeton|"
        r"naturstein|basalt|dr[aä]nmatte|richtzeichnung|radius|typ\s+[a-z0-9]+|"
        r"[0-9]+\s*-\s*zeilig|[0-9]+\s*zeilig|muldenrinne|pultform|kugelgelenk)",
        re.IGNORECASE,
    )
    generic_line_re = re.compile(
        r"(nach unterlagen des ag|liefern und einbauen|fachgerecht herstellen|"
        r"abgerechnet wird|bauwerken nach|herstellen\.$)",
        re.IGNORECASE,
    )

    def _normalize_fragment(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip(" ,;")
        normalized = re.sub(r"\s+([,.;:/])", r"\1", normalized)
        normalized = re.sub(r"(?<=\d)\s+(?=\d)", "", normalized)
        normalized = re.sub(r"(?<=\bDN)\s+(?=\d)", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(?<=\bSN)\s+(?=\d)", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b([0-9]+)\s*-\s*zeilig\b", r"\1-zeilig", normalized, flags=re.IGNORECASE)
        return normalized

    for line in raw_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue
        if _DESCRIPTION_METADATA_LINE_RE.match(stripped):
            continue
        if quantity_line_re.match(stripped):
            continue
        candidates.append(stripped)
        if len(candidates) >= 12:
            break

    if not candidates:
        return fallback or raw_text.strip()

    deduped: list[str] = []
    for line in candidates:
        normalized = _normalize_fragment(line)
        if any(
            normalized == existing
            or normalized in existing
            or existing in normalized
            for existing in deduped
        ):
            if deduped and len(normalized) > len(deduped[-1]) and (
                normalized.startswith(deduped[-1]) or deduped[-1].startswith(normalized)
            ):
                deduped[-1] = normalized
            continue
        deduped.append(normalized)

    if not deduped:
        return fallback or raw_text.strip()

    title = deduped[0]
    details: list[str] = []
    for line in deduped[1:]:
        if generic_line_re.search(line):
            continue
        if not technical_line_re.search(line):
            continue
        if line.lower() in title.lower() or title.lower() in line.lower():
            continue
        details.append(line)
        if len(details) >= 2:
            break

    if details:
        return f"{title}, {', '.join(details)}"[:200]

    return title[:200]


def _is_bad_display_description(value: str | None) -> bool:
    if not value:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    return bool(
        _DESCRIPTION_METADATA_LINE_RE.match(stripped)
        or lowered.startswith("wie zuvor")
        or lowered.startswith("wie position")
        or lowered.startswith("übertrag")
    )


def _human_label_from_params(params: TechnicalParameters) -> str | None:
    subcategory = (params.product_subcategory or "").strip().lower()
    category = (params.product_category or "").strip().lower()
    mapping = {
        "rohr": "Rohr",
        "kanalrohr": "Abwasserkanal",
        "bogen": "Rohrbogen",
        "abzweig": "Abzweig",
        "reduzierstück": "Reduzierstück",
        "reduzierstueck": "Reduzierstück",
        "muffe": "Muffe",
        "muffenstopfen": "Muffenstopfen",
        "revisionsstück": "Reinigungsrohr",
        "revisionsstueck": "Reinigungsrohr",
        "revisionsschacht": "Entwässerungsschacht",
        "schachtunterteil": "Schachtunterteil",
        "schachtring": "Schachtring",
        "konus": "Schachtkonus",
        "ausgleichsring": "Ausgleichsring",
        "schachtfutter": "Schachtfutter",
        "ablauf": "Straßenablauf",
        "aufsatz": "Aufsatz",
        "einlaufkasten": "Einlaufkasten",
        "rinne": "Entwässerungsrinne",
        "abdeckung": "Schachtabdeckung",
        "anschlusssystem": "Anschlusssystem",
        "dränschicht": "Dränschicht",
        "dränmatte": "Dränschicht",
        "dränrohr": "Dränrohr",
    }
    if subcategory in mapping:
        return mapping[subcategory]
    category_mapping = {
        "kanalrohre": "Abwasserkanal",
        "schachtabdeckungen": "Schachtabdeckung",
        "schachtbauteile": "Schachtbauteil",
        "formstuecke": "Formteil",
        "formstücke": "Formteil",
        "straßenentwässerung": "Straßenentwässerung",
        "strassenentwässerung": "Straßenentwässerung",
        "strassenentwaesserung": "Straßenentwässerung",
        "rinnen": "Entwässerungsrinne",
        "dichtungen & zubehoer": "Zubehör",
        "dichtungen & zubehör": "Zubehör",
        "geotextilien": "Geotextil",
        "gasrohre": "Gasrohr",
        "wasserrohre": "Wasserrohr",
        "druckrohre": "Druckrohr",
        "kabelschutz": "Kabelschutzrohr",
    }
    return category_mapping.get(category)


def _append_unique_detail(details: list[str], value: str | None, existing: str) -> None:
    if not value:
        return
    cleaned = re.sub(r"\s+", " ", value).strip(" ,;")
    if not cleaned:
        return
    def _canonical(text: str) -> str:
        text = re.sub(r"^[A-Za-zÄÖÜäöüß /+-]+:\s*", "", text).strip()
        return text.lower()
    lowered_existing = existing.lower()
    lowered_cleaned = cleaned.lower()
    canonical_cleaned = _canonical(cleaned)
    if lowered_cleaned in lowered_existing or canonical_cleaned in lowered_existing:
        return
    if any(_canonical(item) == canonical_cleaned for item in details):
        return
    details.append(cleaned)


def _extract_signal_details_from_raw(raw_text: str, title: str, limit: int = 2) -> list[str]:
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    if not lines:
        return []

    quantity_line_re = re.compile(
        r"^\s*[\d.,]+\s+(Stück|Stck|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b",
        re.IGNORECASE,
    )
    labeled_detail_re = re.compile(
        r"^(abmessungen|maße|masse|material|klasse|belastungsklasse|dicke|stärke|breite|höhe|"
        r"länge|farbton|farbe|typ|anschlussrohr|ablauf|einlaufkasten|stichmaß|stichmass|"
        r"fundament|bettung|gummiauflage|schlammeimer|filtersack)\s*:?\s+(.+)$",
        re.IGNORECASE,
    )

    details: list[str] = []
    normalized_title = re.sub(r"\s+", " ", title).strip().lower()
    for raw_line in lines[1:]:
        if _SKIP_LINE_RE.match(raw_line) or _DESCRIPTION_METADATA_LINE_RE.match(raw_line):
            continue
        if quantity_line_re.match(raw_line):
            continue
        normalized = re.sub(r"\s+", " ", raw_line).strip(" ,;")
        normalized = re.sub(r"\s+([,.;:/])", r"\1", normalized)
        if not normalized:
            continue
        if normalized.lower() in normalized_title or normalized_title in normalized.lower():
            continue
        match = labeled_detail_re.match(normalized)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            _append_unique_detail(details, f"{label}: {value}", title)
        else:
            continue
        if len(details) >= limit:
            break
    return details


def _build_display_description(
    position: LVPosition,
    previous_material_description: str | None = None,
) -> str:
    fallback = position.description
    base = _derive_description_from_raw_text(position.raw_text, fallback)
    params = position.parameters

    fallback_clean = re.sub(r"\s+", " ", fallback or "").strip(" ,;")
    title = fallback_clean if fallback_clean and not _is_bad_display_description(fallback_clean) else base

    human_label = _human_label_from_params(params)
    if _is_bad_display_description(title):
        if previous_material_description and not _is_bad_display_description(previous_material_description):
            title = previous_material_description.split(",")[0].strip()
        elif human_label:
            title = human_label

    title = re.sub(r"\s+", " ", title).strip(" ,;")
    if not title:
        title = fallback_clean or "Position"

    details: list[str] = []
    if params.nominal_diameter_dn is not None and params.secondary_nominal_diameter_dn is not None:
        _append_unique_detail(details, f"DN {params.nominal_diameter_dn}/{params.secondary_nominal_diameter_dn}", title)
    elif params.nominal_diameter_dn is not None:
        _append_unique_detail(details, f"DN {params.nominal_diameter_dn}", title)
    if params.material:
        _append_unique_detail(details, params.material, title)
    if params.stiffness_class_sn is not None:
        _append_unique_detail(details, f"SN{params.stiffness_class_sn}", title)
    if params.norm:
        _append_unique_detail(details, params.norm, title)
    if params.load_class:
        _append_unique_detail(details, params.load_class, title)
    if params.dimensions:
        _append_unique_detail(details, params.dimensions, title)
    if params.system_family and (_is_bad_display_description(fallback_clean) or human_label):
        _append_unique_detail(details, params.system_family, title)
    if params.reference_product and "z. b." not in title.lower():
        _append_unique_detail(details, f"z. B. {params.reference_product}", title)
    for raw_detail in _extract_signal_details_from_raw(position.raw_text, title, limit=2):
        _append_unique_detail(details, raw_detail, title)

    if details:
        return f"{title}, {', '.join(details)}"[:200]
    return title[:200]


def finalize_position_descriptions(positions: list[LVPosition]) -> list[LVPosition]:
    finalized: list[LVPosition] = []
    previous_material_description: str | None = None
    for position in positions:
        if position.position_type == "dienstleistung":
            description = _derive_description_from_raw_text(position.raw_text, position.description)
        else:
            description = _build_display_description(position, previous_material_description)
        updated = position.model_copy(update={"description": description})
        finalized.append(updated)
        if updated.position_type == "material":
            previous_material_description = description
    return finalized


def _extract_raw_texts_from_pages(
    pages: list[str], ordnungszahlen: list[str],
) -> dict[str, str]:
    """Extract the original LV text for each position by finding its ordnungszahl in the PDF pages.

    Returns a dict mapping ordnungszahl → raw text block from the PDF.
    """
    full_text = "\n".join(pages)
    lines = full_text.split("\n")

    # Find ALL OZ-like line starts in the full text
    all_oz_lines: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _OZ_LINE_RE.match(line)
        if m:
            oz_candidate = m.group(1)
            # Must have at least one dot and look like an OZ (not page numbers etc.)
            if "." in oz_candidate:
                all_oz_lines.append((i, oz_candidate))

    wanted = set(ordnungszahlen)

    result: dict[str, str] = {}
    for idx, (start_line, oz) in enumerate(all_oz_lines):
        if oz not in wanted:
            continue

        # End is start of next OZ line (any OZ)
        if idx + 1 < len(all_oz_lines):
            end_line = all_oz_lines[idx + 1][0]
        else:
            end_line = min(start_line + 30, len(lines))

        # Collect description lines — skip headers, dotted lines, blank filler
        block_lines: list[str] = []
        for j in range(start_line, end_line):
            line = lines[j]
            # First line: strip the OZ prefix, keep description text if present
            if j == start_line:
                # Remove OZ number from start of line
                stripped = _OZ_LINE_RE.sub("", line, count=1).strip()
                # If what remains is just quantity + underscores, skip entirely
                if not stripped or "________" in stripped or re.match(r"^[\d.,]+\s+(Stück|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\s", stripped, re.IGNORECASE):
                    continue
                block_lines.append(stripped)
                continue
            if _SKIP_LINE_RE.match(line):
                continue
            # Skip dotted/underscore placeholder lines
            if "________" in line or ".................." in line:
                continue
            # Skip standalone quantity lines like "35,000 m ______"
            if re.match(r"^\s*[\d.,]+\s+(Stück|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b", line, re.IGNORECASE):
                continue
            block_lines.append(line)

        # Trim trailing blank lines
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()

        if block_lines:
            result[oz] = "\n".join(block_lines)

    return result


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

    # Extract original raw text and correct source pages from PDF
    oz_list = [p.ordnungszahl for p in positions]
    raw_texts = _extract_raw_texts_from_pages(pages, oz_list)
    oz_pages = _map_oz_to_page(pdf_bytes, oz_list)
    positions = [
        p.model_copy(update={
            **({"raw_text": raw_texts[p.ordnungszahl]} if p.ordnungszahl in raw_texts else {}),
            **({"description": _derive_description_from_raw_text(raw_texts[p.ordnungszahl], p.description)} if p.ordnungszahl in raw_texts else {}),
            **({"source_page": oz_pages[p.ordnungszahl]} if p.ordnungszahl in oz_pages else {}),
        })
        for p in positions
    ]

    # Validate with heuristics to fill gaps
    positions = _validate_with_heuristics(positions)
    positions = finalize_position_descriptions(positions)

    logger.info(
        "LLM parsing complete: %d positions (%d material, %d dienstleistung)",
        len(positions),
        sum(1 for p in positions if p.position_type == "material"),
        sum(1 for p in positions if p.position_type == "dienstleistung"),
    )

    return positions, metadata
