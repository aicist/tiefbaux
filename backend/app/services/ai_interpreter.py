from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from ..config import settings
from ..schemas import LVPosition, TechnicalParameters

logger = logging.getLogger(__name__)

CATEGORY_KEYWORDS: list[tuple[str, str, str | None]] = [
    ("kanalrohre", "Kanalrohre", "KG-Rohre"),
    ("kg 2000", "Kanalrohre", "KG 2000 Rohre"),
    ("kg-rohr", "Kanalrohre", "KG-Rohre"),
    ("kanalrohr", "Kanalrohre", "KG-Rohre"),
    ("grundrohr", "Kanalrohre", "KG-Rohre"),
    ("straßenablauf", "Straßenentwässerung", "Straßenablauf"),
    ("strassenablauf", "Straßenentwässerung", "Straßenablauf"),
    ("schachtabdeckung", "Schachtabdeckungen", "Guss rund"),
    ("schachtdeckel", "Schachtabdeckungen", "Guss rund"),
    ("schachtunterteil", "Schachtbauteile", "Schachtunterteil"),
    ("schachtring", "Schachtbauteile", "Schachtring"),
    ("konus", "Schachtbauteile", "Schachthals/Konus"),
    ("schachthals", "Schachtbauteile", "Schachthals/Konus"),
    ("auflagering", "Schachtbauteile", "Auflagering"),
    ("kontrollschacht", "Schachtbauteile", "KG-Schachtboden"),
    ("schachtboden", "Schachtbauteile", "KG-Schachtboden"),
    ("formstück", "Formstücke", None),
    ("formstueck", "Formstücke", None),
    ("bogen", "Formstücke", None),
    ("abzweig", "Formstücke", None),
    ("muffe", "Formstücke", None),
    ("reduktion", "Formstücke", None),
    ("rinne", "Rinnen", "Entwässerungsrinne"),
    ("rost", "Rinnen", "Rinnenrost"),
    ("dichtung", "Dichtungen & Zubehör", "Rohrdichtung"),
    ("rückstauverschluss", "Dichtungen & Zubehör", "Rückstauverschluss"),
    ("rueckstauverschluss", "Dichtungen & Zubehör", "Rückstauverschluss"),
    ("geotextil", "Geotextilien", None),
    ("vlies", "Geotextilien", None),
    ("rohr", "Kanalrohre", "KG-Rohre"),
    ("schacht", "Schachtbauteile", None),
]

MATERIAL_KEYWORDS = {
    "pp": "PP",
    "pvc": "PVC-U",
    "pvc-u": "PVC-U",
    "stahlbeton": "Stahlbeton",
    "beton": "Beton",
    "gusseisen": "Gusseisen",
    "guss": "Gusseisen",
    "hdpe": "HDPE",
    "polyethylen": "HDPE",
    "pe": "HDPE",
    "steinzeug": "Steinzeug",
}

LOAD_CLASSES = ("A15", "B125", "C250", "D400", "E600", "F900")
SERVICE_KEYWORDS = (
    "abbruch",
    "entsorgung",
    "demont",
    "stundenlohn",
    "baustellen",
    "vorhaltung",
    "transport",
    "rueckbau",
    "rückbau",
    "sperrung",
    "einmessen",
    "verdichten",
    "kennzeichnen",
)

NORM_RE = re.compile(r"(DIN\s*(?:EN\s*)?\d+(?:-\d+)?)", re.IGNORECASE)
DN_RE = re.compile(r"\bDN\s*([0-9]{2,4})\b", re.IGNORECASE)
DIM_RE = re.compile(r"([0-9]{2,4}\s*[x/]|H\s*=\s*[0-9]{2,4}|Ø\s*[0-9]{2,4})", re.IGNORECASE)


class InterpretationError(Exception):
    pass


def _normalize_json_content(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise InterpretationError("No JSON object found in model response")
    return stripped[start : end + 1]


def _normalize_json_array(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped.replace("json", "", 1).strip()

    start = stripped.find("[")
    end = stripped.rfind("]")
    if start == -1 or end == -1 or end <= start:
        raise InterpretationError("No JSON array found in model response")
    return stripped[start : end + 1]


def _infer_with_heuristics(position: LVPosition) -> TechnicalParameters:
    text = f"{position.description}\n{position.raw_text}".lower()
    has_strong_product_signal = bool(DN_RE.search(position.raw_text)) or any(
        load_class.lower() in text for load_class in LOAD_CLASSES
    )
    is_service_position = any(keyword in text for keyword in SERVICE_KEYWORDS) and not has_strong_product_signal

    category = None
    subcategory = None
    if not is_service_position:
        for keyword, category_value, subcategory_value in CATEGORY_KEYWORDS:
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                category = category_value
                subcategory = subcategory_value
                break

    material = None if is_service_position else next((value for key, value in MATERIAL_KEYWORDS.items() if key in text), None)

    dn_match = DN_RE.search(position.raw_text)
    load_class = next((klass for klass in LOAD_CLASSES if klass.lower() in text), None)
    norm_match = NORM_RE.search(position.raw_text)
    dim_match = DIM_RE.search(position.raw_text)

    install_area = None
    if "fahrbahn" in text:
        install_area = "Fahrbahn"
    elif "gehweg" in text:
        install_area = "Gehweg"
    elif "erdeinbau" in text or "kanal" in text:
        install_area = "Erdeinbau"

    reference = None
    for candidate in ("GEFAguard", "Multitop", "FASERFIX", "KG 2000", "ACO", "Wavin", "Ostendorf"):
        if candidate.lower() in text:
            reference = candidate
            break

    return TechnicalParameters(
        product_category=category,
        product_subcategory=subcategory,
        material=material,
        nominal_diameter_dn=int(dn_match.group(1)) if dn_match else None,
        load_class=load_class,
        norm=norm_match.group(1).upper() if norm_match else None,
        dimensions=dim_match.group(0) if dim_match else None,
        quantity=position.quantity,
        unit=position.unit,
        reference_product=reference,
        installation_area=install_area,
    )


def _call_gemini_batch(positions: list[LVPosition]) -> list[dict[str, Any]]:
    if not settings.gemini_api_key:
        raise InterpretationError("GEMINI_API_KEY not configured")

    instruction = (
        "Du bist ein erfahrener Tiefbau-Fachberater bei einem Baustoffhaendler. "
        "Analysiere die folgenden LV-Positionen und extrahiere pro Position die technischen Parameter. "
        "Gib ein JSON-Array zurueck mit einem Objekt pro Position (gleiche Reihenfolge). "
        "Jedes Objekt hat diese Keys: "
        "product_category, product_subcategory, material, nominal_diameter_dn (Integer oder null), "
        "load_class, norm, stiffness_class_sn (Integer oder null, z.B. 4/8/16 fuer SN4/SN8/SN16), "
        "dimensions, color, reference_product, installation_area, sortiment_relevant. "
        "Verwende fuer product_category nur: Kanalrohre, Schachtabdeckungen, Schachtbauteile, "
        "Formstücke, Straßenentwässerung, Rinnen, Dichtungen & Zubehör. "
        "Setze null wenn ein Wert nicht erkennbar ist.\n\n"
        "sortiment_relevant (boolean): Ist diese Position ein Produkt das ein Tiefbau-/Baustoffhaendler "
        "fuehren wuerde (Rohre, Schaechte, Formstücke, Abdeckungen, Rinnen, Dichtungen, Geotextilien, "
        "Druckrohre, Kabelschutzrohre)? "
        "NICHT relevant sind: Stuetzmauern, Fundamente, Bordsteine, Pflaster, Asphalt, Oberboden, "
        "Rasen, Poller, Blockstufen, Zaeune, Beleuchtung, Sand/Kies/Schotter (als Schuettgut), "
        "Hydrantenarmaturen, Hausanschlussgarnituren, reine Einbau-/Montagearbeiten. "
        "Setze true wenn es ein Handelsprodukt ist, false wenn nicht."
    )

    pos_texts = []
    for i, pos in enumerate(positions):
        pos_texts.append(
            f"Position {i+1}:\n"
            f"  Ordnungszahl: {pos.ordnungszahl}\n"
            f"  Beschreibung: {pos.description}\n"
            f"  Rohtext: {pos.raw_text}\n"
            f"  Menge: {pos.quantity} {pos.unit or ''}"
        )

    prompt = "Analysiere diese LV-Positionen und gib nur ein JSON-Array zurueck:\n\n" + "\n\n".join(pos_texts)

    payload = {
        "system_instruction": {"parts": [{"text": instruction}]},
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
    with httpx.Client(timeout=45) as client:
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


def enrich_positions_with_parameters(positions: list[LVPosition]) -> list[LVPosition]:
    enriched: list[LVPosition] = []

    # First pass: heuristic enrichment for all positions
    heuristic_results: list[TechnicalParameters] = []
    for position in positions:
        heuristic_results.append(_infer_with_heuristics(position))

    # Second pass: batch Gemini enrichment
    if settings.gemini_api_key:
        batch_size = 15
        ai_results: list[dict[str, Any] | None] = [None] * len(positions)

        for batch_start in range(0, len(positions), batch_size):
            batch = positions[batch_start : batch_start + batch_size]
            try:
                batch_results = _call_gemini_batch(batch)
                for i, result in enumerate(batch_results):
                    if batch_start + i < len(positions):
                        ai_results[batch_start + i] = result
            except InterpretationError as exc:
                logger.warning("Gemini batch %d-%d failed, using heuristics: %s", batch_start, batch_start + len(batch), exc)

        # Merge AI results with heuristics
        for i, position in enumerate(positions):
            interpreted = heuristic_results[i]
            ai_data = ai_results[i]
            if ai_data and isinstance(ai_data, dict):
                try:
                    ai_data.setdefault("quantity", position.quantity)
                    ai_data.setdefault("unit", position.unit)
                    ai_params = TechnicalParameters(**{k: v for k, v in ai_data.items() if k in TechnicalParameters.model_fields})
                    merged = interpreted.model_dump()
                    merged.update({k: v for k, v in ai_params.model_dump().items() if v not in (None, "")})
                    interpreted = TechnicalParameters(**merged)
                except Exception as exc:
                    logger.warning("Failed to merge AI params for position %s: %s", position.ordnungszahl, exc)

            enriched.append(position.model_copy(update={"parameters": interpreted}))
    else:
        for i, position in enumerate(positions):
            enriched.append(position.model_copy(update={"parameters": heuristic_results[i]}))

    return enriched
