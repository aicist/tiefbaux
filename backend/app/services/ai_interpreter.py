from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

from ..config import settings
from ..schemas import ComponentRequirement, LVPosition, TechnicalParameters

logger = logging.getLogger(__name__)


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

CATEGORY_KEYWORDS: list[tuple[str, str, str | None]] = [
    ("entwässerungsschacht", "Schachtbauteile", "Entwässerungsschacht"),
    ("entwaesserungsschacht", "Schachtbauteile", "Entwässerungsschacht"),
    ("revisionsschacht", "Schachtbauteile", "Revisionsschacht"),
    ("revischacht", "Schachtbauteile", "Revisionsschacht"),
    ("froschklappe", "Formstücke", "Rückstauverschluss"),
    ("rohrklappe", "Formstücke", "Rückstauverschluss"),
    ("rückstauverschluss", "Formstücke", "Rückstauverschluss"),
    ("rueckstauverschluss", "Formstücke", "Rückstauverschluss"),
    ("absperrschieber", "Formstücke", "Absperrarmaturen"),
    ("kanalrohre", "Kanalrohre", "KG-Rohre"),
    ("kg 2000", "Kanalrohre", "KG 2000 Rohre"),
    ("kg-rohr", "Kanalrohre", "KG-Rohre"),
    ("kanalrohr", "Kanalrohre", "KG-Rohre"),
    ("grundrohr", "Kanalrohre", "KG-Rohre"),
    ("rohrleitung", "Kanalrohre", "KG-Rohre"),
    ("straßenablauf", "Straßenentwässerung", "Straßenablauf"),
    ("strassenablauf", "Straßenentwässerung", "Straßenablauf"),
    ("betonschacht", "Schachtbauteile", "Betonschacht"),
    ("kunststoffschacht", "Schachtbauteile", "Kunststoffschacht"),
    ("schachtabdeckung", "Schachtabdeckungen", "Guss rund"),
    ("schachtdeckel", "Schachtabdeckungen", "Guss rund"),
    ("schachtunterteil", "Schachtbauteile", "Schachtunterteil"),
    ("betonschachtring", "Schachtbauteile", "Schachtring"),
    ("schachtring", "Schachtbauteile", "Schachtring"),
    ("konus", "Schachtbauteile", "Schachthals/Konus"),
    ("schachthals", "Schachtbauteile", "Schachthals/Konus"),
    ("auflagering", "Schachtbauteile", "Auflagering"),
    ("kontrollschacht", "Schachtbauteile", "KG-Schachtboden"),
    ("schachtboden", "Schachtbauteile", "KG-Schachtboden"),
    ("schachtfutter", "Schachtbauteile", "Schachtfutter"),
    ("übergangsstück", "Formstücke", "Übergangsstück"),
    ("uebergangsstueck", "Formstücke", "Übergangsstück"),
    ("passstück", "Formstücke", "Passstück"),
    ("passstueck", "Formstücke", "Passstück"),
    ("reduzierstück", "Formstücke", "Reduzierstück"),
    ("reduzierstueck", "Formstücke", "Reduzierstück"),
    ("reduktion", "Formstücke", "Reduzierstück"),
    ("formstück", "Formstücke", None),
    ("formstueck", "Formstücke", None),
    ("rohrbogen", "Formstücke", "Rohrbogen"),
    ("bogen", "Formstücke", "Rohrbogen"),
    ("abzweig", "Formstücke", "Abzweig"),
    ("muffe", "Formstücke", "Muffe"),
    ("schwerlastrinne", "Rinnen", "Schwerlastrinne"),
    ("entwässerungsrinne", "Rinnen", "Entwässerungsrinne"),
    ("entwasserungsrinne", "Rinnen", "Entwässerungsrinne"),
    ("hofablauf", "Straßenentwässerung", "Hofablauf"),
    ("sinkkasten", "Straßenentwässerung", "Sinkkasten"),
    ("anschlusskasten", "Straßenentwässerung", "Anschlusskasten"),
    ("rinne", "Rinnen", "Entwässerungsrinne"),
    ("rost", "Rinnen", "Rinnenrost"),
    ("dichtung", "Dichtungen & Zubehör", "Rohrdichtung"),
    ("geotextil", "Geotextilien", None),
    ("vlies", "Geotextilien", None),
    ("rohr", "Kanalrohre", "KG-Rohre"),
    ("schacht", "Schachtbauteile", None),
]

MATERIAL_KEYWORDS = {
    "pvc-u": "PVC-U",
    "polymerbeton": "Polymerbeton",
    "stahlbeton": "Stahlbeton",
    "beton": "Beton",
    "gusseisen": "Gusseisen",
    "polyethylen": "HDPE",
    "pe-hd": "HDPE",
    "pe 100": "HDPE",
    "pe100": "HDPE",
    "pe-rohr": "HDPE",
    "steinzeug": "Steinzeug",
}

# Keywords that need word-boundary matching (short strings prone to substring false-positives)
# NOTE: "pp" must be word-boundary-only — otherwise substrings like "klappe"/"schuppen"/"stoppel"
# would incorrectly set material to PP.
# NOTE: "pvc"/"guss" also lenient — substrings like "gussanschluss" should not force Gusseisen.
_MATERIAL_REGEX_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bpe\b", re.IGNORECASE), "HDPE"),
    (re.compile(r"\bpp\b", re.IGNORECASE), "PP"),
    (re.compile(r"\bpvc\b", re.IGNORECASE), "PVC-U"),
    (re.compile(r"\bguss\b", re.IGNORECASE), "Gusseisen"),
]

LOAD_CLASSES = ("A15", "B125", "C250", "D400", "D900", "E600", "F900")
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
    "anschlussarbeiten",
    "kopfloch",
    "schnittkanten",
    "schnitt ausklinkung",
    "plattendruckversuch",
    "lastplattendruck",
    "druckversuch",
    "regulieren",
    "überarbeiten",
    "ueberarbeiten",
    "prüfergebnisse",
    "pruefergebnisse",
    "tragschicht",
)

NON_CATALOG_KEYWORDS = (
    "bordstein",
    "randstein",
    "pflaster",
    "pflasterrinne",
    "pflasterinne",
    "plattenband",
    "betonplatten",
    "tragschicht",
    "mauerscheiben",
    "fertiggarage",
    "bitumenfugenband",
    "schutzlage",
)

NORM_RE = re.compile(r"(DIN\s*(?:EN\s*)?\d+(?:-\d+)?)", re.IGNORECASE)
DN_RE = re.compile(r"\bDN\s*([0-9]{1,2}\.?[0-9]{2,3})\b", re.IGNORECASE)
DIM_RE = re.compile(r"([0-9]{2,4}\s*x\s*[0-9]{2,4}|H\s*=\s*[0-9]{2,4}|Ø\s*[0-9]{2,4})", re.IGNORECASE)
PIPE_LENGTH_RE = re.compile(
    r"(?:baul[äa]nge|rohrl[äa]nge|l[äa]nge)[:\s]*(\d+)\s*(mm|m)\b",
    re.IGNORECASE,
)
ANGLE_RE = re.compile(r"(\d+)\s*(?:°|[Gg]rad)")
APPLICATION_KEYWORDS: dict[str, str] = {
    "trinkwasser": "Trinkwasser",
    "gas": "Gas",
    "abwasser": "Abwasser",
    "schmutzwasser": "Abwasser",
    "regenwasser": "Regenwasser",
    "mischwasser": "Abwasser",
}

SYSTEM_FAMILY_KEYWORDS: list[tuple[str, str]] = [
    ("powerdrain seal", "Aco Powerdrain"),
    ("powerdrain", "Aco Powerdrain"),
    ("multiline", "Aco Multiline"),
    ("faserfix", "Faserfix"),
    ("recyfix", "Recyfix"),
    ("awadukt hpp", "AWADUKT HPP"),
    ("x-stream", "Wavin X-Stream"),
    ("tegra", "Wavin Tegra"),
    ("kg 2000", "KG 2000"),
    ("kg pvc", "KG PVC-U"),
    ("kg-rohr", "KG PVC-U"),
    ("kg rohr", "KG PVC-U"),
    ("pp sn10", "PP SN10 grün"),
    ("green connect 2000", "Wavin Green Connect 2000"),
    ("green connect", "Green Connect"),
    ("certaro", "Wavin Certaro"),
    ("acaro pp blue", "Wavin Acaro PP Blue"),
    ("acaro pp", "Wavin Acaro PP"),
    ("acaro", "Wavin Acaro"),
    ("safe tech rc", "Wavin SafeTech RC"),
    ("safetech rc", "Wavin SafeTech RC"),
    ("ts doq", "Wavin TS DOQ"),
    ("pe 100-rc", "Wavin PE 100-RC Druckrohr"),
    ("pe100-rc", "Wavin PE 100-RC Druckrohr"),
    ("pe 100", "Wavin PE 100 Druckrohr"),
    ("pe100", "Wavin PE 100 Druckrohr"),
    ("q-bic plus", "Wavin Q-Bic Plus"),
    ("sx 400", "Wavin SX 400"),
    ("xs 400", "Wavin SX 400"),
]

CONNECTION_TYPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsteckmuffe\b", re.IGNORECASE), "Steckmuffe"),
    (re.compile(r"\bdoppelmuffe\b", re.IGNORECASE), "Doppelmuffe"),
    (re.compile(r"\bueberschiebmuffe\b|\büberschiebmuffe\b", re.IGNORECASE), "Überschiebmuffe"),
    (re.compile(r"\bmuffe\b", re.IGNORECASE), "Muffe"),
    (re.compile(r"\bflansch(?:anschluss)?\b", re.IGNORECASE), "Flansch"),
    (re.compile(r"\bspitzende\b", re.IGNORECASE), "Spitzende"),
    (re.compile(r"\bklemm(?:verbindung)?\b", re.IGNORECASE), "Klemmverbindung"),
]

SEAL_TYPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bgleitringdichtung\b", re.IGNORECASE), "Gleitringdichtung"),
    (re.compile(r"\blippendichtung\b", re.IGNORECASE), "Lippendichtung"),
    (re.compile(r"\bprofildichtung\b|\bprofilring\b", re.IGNORECASE), "Profildichtung"),
    (re.compile(r"\bdoppeldichtung\b", re.IGNORECASE), "Doppeldichtung"),
]

COMPATIBLE_SYSTEM_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bht\b", re.IGNORECASE), "HT"),
    (re.compile(r"\bkg\b", re.IGNORECASE), "KG"),
    (re.compile(r"\bpvc-?kg\b", re.IGNORECASE), "PVC-KG"),
    (re.compile(r"\bpe-?hd\b", re.IGNORECASE), "PE-HD"),
    (re.compile(r"\bgussrohr\b", re.IGNORECASE), "Gussrohr"),
    (re.compile(r"\bbetonrohr\b", re.IGNORECASE), "Betonrohr"),
    (re.compile(r"\bsteinzeug\b", re.IGNORECASE), "Steinzeug"),
]

SECONDARY_DN_SLASH_RE = re.compile(r"\bDN\s*(\d{2,4})\s*[/x]\s*(\d{2,4})\b", re.IGNORECASE)
CONNECTION_DN_RE = re.compile(r"\banschlu(?:ss|ß)(?:\s*ein-/ausgang)?[:\s]*(\d{2,4})\s*(?:mm|dn)?\b", re.IGNORECASE)
STRUCTURE_DN_RE = re.compile(r"\b(?:xs|sx)\s*(\d{3,4})\b|\((\d{3,4})\s*mm\)|\bDN\s*(\d{1,2}\.?\d{3})\b", re.IGNORECASE)
# Prefer "Lichter Schachtdurchmesser" / "Schachtdurchmesser" for shaft DN
_SHAFT_DN_RE = re.compile(r"(?:lichter?\s+)?schachtdurchmesser[:\s]*DN?\s*([0-9]{1,2}\.?[0-9]{3})", re.IGNORECASE)
COUNT_RE_TEMPLATES = {
    "schachtring": re.compile(r"(\d+)\s*(?:x\s*)?schachtringe?\b", re.IGNORECASE),
    "rohreinfuehrung": re.compile(r"(\d+)\s*rohreinf[üu]hrungen?\b", re.IGNORECASE),
}


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


_SYSTEM_FAMILY_COMPAT_MARKERS = (
    "anschluss für",
    "anschluss fuer",
    "zum anschluss",
    "passend für",
    "passend fuer",
    "anschluss an",
    "kompatibel",
    "für pvc-kg",
    "fuer pvc-kg",
    "pvc-kg-rohr",
    "pe-hd-rohr",
)


def _infer_system_family(text: str) -> str | None:
    # When the text frames the match as a compatibility/connection statement,
    # the keyword describes what the product connects TO, not what the product IS.
    is_compat_context = any(marker in text for marker in _SYSTEM_FAMILY_COMPAT_MARKERS)
    for keyword, system_family in SYSTEM_FAMILY_KEYWORDS:
        # Use word boundaries to avoid "kg-rohr" matching inside "pvc-kg-rohr"
        if re.search(rf"(?<![a-z0-9-]){re.escape(keyword)}(?![a-z0-9-])", text):
            if is_compat_context and system_family in {"KG PVC-U", "KG 2000", "HDPE"}:
                continue
            return system_family
    return None


def _infer_connection_type(text: str) -> str | None:
    for pattern, value in CONNECTION_TYPE_PATTERNS:
        if pattern.search(text):
            return value
    return None


def _infer_seal_type(text: str) -> str | None:
    for pattern, value in SEAL_TYPE_PATTERNS:
        if pattern.search(text):
            return value
    return None


def _infer_compatible_systems(text: str) -> list[str] | None:
    found: list[str] = []
    for pattern, value in COMPATIBLE_SYSTEM_KEYWORDS:
        if pattern.search(text) and value not in found:
            found.append(value)
    return found or None


def _infer_secondary_dn(text: str, category: str | None, subcategory: str | None) -> int | None:
    lower_category = (category or "").lower()
    lower_subcategory = (subcategory or "").lower()
    is_connection_like = any(
        token in lower_subcategory or token in lower_category
        for token in ("form", "anschluss", "abzweig", "reduk", "rückstau", "rueckstau", "absperr")
    ) or any(token in text for token in ("anschluss", "abzweig", "reduk", "froschklappe", "rückstau", "rueckstau"))

    slash_match = SECONDARY_DN_SLASH_RE.search(text)
    if slash_match and is_connection_like:
        return int(slash_match.group(2))

    connection_match = CONNECTION_DN_RE.search(text)
    if connection_match:
        return int(connection_match.group(1))

    return None


def _infer_structure_dn(text: str, fallback_dn: int | None = None) -> int | None:
    # Prefer explicit "Lichter Schachtdurchmesser" if present
    shaft_match = _SHAFT_DN_RE.search(text)
    if shaft_match:
        return int(shaft_match.group(1).replace(".", ""))
    candidates: list[int] = []
    for match in STRUCTURE_DN_RE.finditer(text):
        for group in match.groups():
            if not group:
                continue
            value = int(group.replace(".", ""))
            if value >= 300:
                candidates.append(value)
    if candidates:
        return candidates[0]
    return fallback_dn


def _extract_component_quantity(text: str, component_key: str, default: int = 1) -> int:
    pattern = COUNT_RE_TEMPLATES.get(component_key)
    if not pattern:
        return default
    match = pattern.search(text)
    return int(match.group(1)) if match else default


def _make_component(
    name: str,
    *,
    description: str | None = None,
    category: str | None = None,
    subcategory: str | None = None,
    dn: int | None = None,
    secondary_dn: int | None = None,
    quantity: int = 1,
    material: str | None = None,
    system_family: str | None = None,
    load_class: str | None = None,
    dimensions: str | None = None,
    connection_type: str | None = None,
    installation_area: str | None = None,
) -> ComponentRequirement:
    return ComponentRequirement(
        component_name=name,
        description=description or name,
        product_category=category,
        product_subcategory=subcategory,
        nominal_diameter_dn=dn,
        secondary_nominal_diameter_dn=secondary_dn,
        quantity=quantity,
        material=material,
        system_family=system_family,
        load_class=load_class,
        dimensions=dimensions,
        connection_type=connection_type,
        installation_area=installation_area,
    )


def _infer_components(
    position: LVPosition,
    *,
    category: str | None,
    subcategory: str | None,
    material: str | None,
    nominal_dn: int | None,
    secondary_dn: int | None,
    load_class: str | None,
    dimensions: str | None,
    system_family: str | None,
    installation_area: str | None,
    connection_type: str | None,
) -> list[ComponentRequirement] | None:
    text = f"{position.description}\n{position.raw_text}".lower()
    structure_dn = _infer_structure_dn(text, nominal_dn)
    components: list[ComponentRequirement] = []

    is_revisionsschacht = any(token in text for token in ("revisionsschacht", "revischacht", "rev.-schacht"))
    is_betonschacht = (
        subcategory == "Betonschacht"
        or "betonschacht" in text
        or ("entwaesserungsschacht" in text and (material in {"Beton", "Stahlbeton"} or "beton" in text))
        or ("entwässerungsschacht" in text and (material in {"Beton", "Stahlbeton"} or "beton" in text))
    )
    is_kunststoffschacht = (
        subcategory == "Kunststoffschacht"
        or "kunststoffschacht" in text
        or (system_family or "").strip().lower() == "awaschacht"
    )
    is_shaft_position = is_revisionsschacht or is_betonschacht or is_kunststoffschacht
    shaft_dn = nominal_dn or structure_dn
    cover_dn = 625 if "625" in text else structure_dn or nominal_dn
    if is_shaft_position:
        has_bottom = any(token in text for token in ("unterteil", "schachtring mit boden", "boden"))
        has_ring = ("schachtring" in text and not is_kunststoffschacht) or is_betonschacht
        has_shaft_pipe = "schachtrohr" in text or (is_kunststoffschacht and structure_dn is not None)
        has_cone = any(token in text for token in ("konus", "schaftkonus", "schachthals")) or is_betonschacht
        has_cover = any(token in text for token in ("deckel", "abdeckung", "rahmen d400", "lichte weite"))
        has_depth = any(token in text for token in ("schachttiefe", "schachthöhe", "schachthoehe", "einbautiefe", "tiefe"))

        if has_bottom or structure_dn is not None:
            components.append(_make_component(
                "Schachtunterteil",
                description=f"Schachtunterteil DN {shaft_dn or ''} {system_family or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachtunterteil",
                dn=shaft_dn,
                secondary_dn=secondary_dn,
                quantity=1,
                material=material,
                system_family=system_family,
                installation_area=installation_area,
                connection_type=connection_type,
            ))
        if has_ring:
            components.append(_make_component(
                "Schachtring",
                description=f"Schachtring DN {shaft_dn or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachtring",
                dn=shaft_dn,
                quantity=_extract_component_quantity(text, "schachtring"),
                material=material,
                system_family=system_family,
                installation_area=installation_area,
            ))
        if has_shaft_pipe or (has_depth and is_kunststoffschacht and structure_dn is not None):
            components.append(_make_component(
                "Schachtrohr",
                description=f"Schachtrohr DN {shaft_dn or ''} {system_family or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachtrohr",
                dn=shaft_dn,
                quantity=1,
                material=material,
                system_family=system_family,
                installation_area=installation_area,
            ))
        if has_cone and not is_kunststoffschacht:
            components.append(_make_component(
                "Konus",
                description=f"Konus DN {shaft_dn or ''} {dimensions or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachthals/Konus",
                dn=shaft_dn,
                quantity=1,
                material=material,
                system_family=system_family,
                installation_area=installation_area,
                dimensions=dimensions,
            ))
        if "schachtfutter" in text:
            components.append(_make_component(
                "Schachtfutter",
                description=f"Schachtfutter {system_family or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachtfutter",
                dn=secondary_dn,
                quantity=1,
                material=None,
                system_family=system_family,
                installation_area=installation_area,
            ))
        if has_cover:
            components.append(_make_component(
                "Abdeckung",
                description=f"Abdeckung {load_class or ''} DN {cover_dn or ''}".strip(),
                category="Schachtabdeckungen",
                subcategory="Abdeckung",
                dn=cover_dn,
                quantity=1,
                material="Gusseisen" if "guss" in text else None,
                system_family=system_family,
                load_class=load_class,
                installation_area=installation_area,
            ))
    is_ablaufkombination = "ablaufkombination" in text or ("bestehend aus" in text and "aufsatz" in text and "boden" in text)
    if is_ablaufkombination:
        if "aufsatz" in text:
            components.append(_make_component(
                "Aufsatz",
                description=f"Aufsatz {dimensions or ''} {load_class or ''} {position.parameters.reference_product or ''}".strip(),
                category="Straßenentwässerung",
                subcategory="Straßenablauf",
                dn=structure_dn or nominal_dn,
                quantity=1,
                material=material,
                load_class=load_class,
                dimensions=dimensions,
                installation_area=installation_area,
            ))
        if "ring" in text:
            components.append(_make_component(
                "Ring",
                description=f"Ring DN {structure_dn or nominal_dn or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachtring",
                dn=structure_dn or nominal_dn,
                quantity=1,
                material=material,
                installation_area=installation_area,
            ))
        if any(token in text for token in ("schaftkonus", "konus")):
            components.append(_make_component(
                "Schaftkonus",
                description=f"Schaftkonus DN {structure_dn or nominal_dn or ''}".strip(),
                category="Schachtbauteile",
                subcategory="Schachthals/Konus",
                dn=structure_dn or nominal_dn,
                quantity=1,
                material=material,
                installation_area=installation_area,
            ))
        if "boden" in text:
            components.append(_make_component(
                "Boden",
                description=f"Boden mit Anschluss DN {secondary_dn or ''}".strip(),
                category="Straßenentwässerung",
                subcategory="Straßenablauf",
                dn=structure_dn or nominal_dn,
                secondary_dn=secondary_dn,
                quantity=1,
                material=material,
                load_class=load_class,
                installation_area=installation_area,
            ))
        if "eimer" in text:
            components.append(_make_component(
                "Eimer",
                description="Schmutzfangeimer",
                category="Straßenentwässerung",
                subcategory="Schmutzfangeimer",
                quantity=1,
                material="Stahl" if "verzinkt" in text else None,
                installation_area=installation_area,
            ))

    is_street_drain_top = any(token in text for token in ("straßenablauf", "strassenablauf")) and "aufsatz" in text
    if is_street_drain_top and not is_ablaufkombination:
        components.append(_make_component(
            "Aufsatz",
            description=f"Aufsatz {dimensions or ''} {load_class or ''}".strip(),
            category="Straßenentwässerung",
            subcategory="Straßenablauf",
            dn=None,
            quantity=1,
            material=material,
            load_class=load_class,
            dimensions=dimensions,
            installation_area=installation_area,
        ))
        if "eimer" in text:
            components.append(_make_component(
                "Schmutzfangeimer",
                description="Schmutzfangeimer",
                category="Straßenentwässerung",
                subcategory="Schmutzfangeimer",
                quantity=1,
                material="Stahl" if "verzinkt" in text else None,
                installation_area=installation_area,
            ))

    is_rinne_system = any(token in text for token in ("entwässerungsrinne", "entwaesserungsrinne", "powerdrain", "multiline"))
    if is_rinne_system and any(token in text for token in ("einlaufkasten", "rost", "stirnwand", "stirnwänden", "stirnwaenden")):
        components.append(_make_component(
            "Rinne",
            description=f"Entwässerungsrinne DN {nominal_dn or ''} {load_class or ''} {system_family or position.parameters.reference_product or ''}".strip(),
            category="Rinnen",
            subcategory="Entwässerungsrinne",
            dn=nominal_dn,
            quantity=1,
            material=material,
            system_family=system_family or position.parameters.reference_product,
            load_class=load_class,
            installation_area=installation_area,
        ))

    is_einlaufkasten = any(token in text for token in ("einlaufkasten", "anschlusskasten", "sinkkasten", "schlammfangkasten"))
    if is_einlaufkasten:
        components.append(_make_component(
            "Einlaufkasten",
            description=f"Einlaufkasten DN {nominal_dn or secondary_dn or ''} {load_class or ''}".strip(),
            category="Straßenentwässerung",
            subcategory="Einlaufkasten",
            dn=nominal_dn or secondary_dn,
            quantity=1,
            material=None,
            system_family=system_family,
            load_class=load_class,
            dimensions=dimensions,
            installation_area=installation_area,
        ))
        if any(token in text for token in ("schmutzeimer", "schmutzfangeimer", "schlammfang", "eimer")):
            components.append(_make_component(
                "Schmutzfangeimer",
                description="Schmutzfangeimer",
                category="Straßenentwässerung",
                subcategory="Schmutzfangeimer",
                quantity=1,
                material="Stahl" if "verzinkt" in text else None,
                system_family=system_family,
                installation_area=installation_area,
            ))
        if "geruchsverschluss" in text:
            components.append(_make_component(
                "Geruchsverschluss",
                description=f"Geruchsverschluss DN {secondary_dn or nominal_dn or ''}".strip(),
                category="Straßenentwässerung",
                subcategory="Hofablauf",
                dn=secondary_dn or nominal_dn,
                quantity=1,
                system_family=system_family,
                installation_area=installation_area,
            ))
        if "rost" in text:
            components.append(_make_component(
                "Rost",
                description=f"Rost {dimensions or ''} {load_class or ''}".strip(),
                category="Rinnen",
                subcategory="Rost",
                dn=nominal_dn,
                quantity=1,
                load_class=load_class,
                system_family=system_family,
                dimensions=dimensions,
                installation_area=installation_area,
            ))
        if any(token in text for token in ("stirnwand", "stirnwänden", "stirnwaenden")):
            components.append(_make_component(
                "Stirnwand",
                description="Stirnwand",
                category="Rinnen",
                subcategory="Stirnwand",
                dn=nominal_dn,
                quantity=1,
                system_family=system_family,
                installation_area=installation_area,
            ))

    if len(components) <= 1:
        return None

    deduped: list[ComponentRequirement] = []
    seen: set[tuple[str, str | None, int | None, str | None]] = set()
    for comp in components:
        key = (
            comp.component_name,
            comp.product_subcategory,
            comp.nominal_diameter_dn,
            comp.system_family,
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(comp)

    return deduped if len(deduped) > 1 else None


def _infer_with_heuristics(position: LVPosition) -> TechnicalParameters:
    text = f"{position.description}\n{position.raw_text}".lower()
    existing = position.parameters
    has_strong_product_signal = bool(DN_RE.search(position.raw_text)) or any(
        load_class.lower() in text for load_class in LOAD_CLASSES
    )
    is_service_position = any(keyword in text for keyword in SERVICE_KEYWORDS) and not has_strong_product_signal

    category = None
    subcategory = None
    # Keywords that contain "rinne" but are NOT drainage channels (Wavin Rinnen)
    _NOT_DRAINAGE_RINNE = (
        "pflasterrinne", "pflasterinne", "bitumenfugenband", "bitumenfuge",
        "muldenrinne", "bordsteinrinne", "pendelrinne",
    )
    is_false_rinne = any(kw in text for kw in _NOT_DRAINAGE_RINNE)
    if not is_service_position:
        for keyword, category_value, subcategory_value in CATEGORY_KEYWORDS:
            if is_false_rinne and category_value == "Rinnen":
                continue
            if re.search(rf"\b{re.escape(keyword)}\b", text):
                category = category_value
                subcategory = subcategory_value
                break
    if existing.product_category and category is None:
        category = existing.product_category
    if existing.product_subcategory and subcategory is None:
        subcategory = existing.product_subcategory

    material = None
    if not is_service_position:
        # Check longer/safer keywords first (substring match is fine for these)
        for key, value in MATERIAL_KEYWORDS.items():
            if key in text:
                material = value
                break
        # Then check short keywords with word-boundary regex
        if material is None:
            for pattern, value in _MATERIAL_REGEX_KEYWORDS:
                if pattern.search(text):
                    material = value
                    break
    if existing.material and material is None:
        material = existing.material

    dn_match = DN_RE.search(position.raw_text)
    load_class = next((klass for klass in LOAD_CLASSES if klass.lower() in text), None)
    norm_match = NORM_RE.search(position.raw_text)
    dim_match = DIM_RE.search(position.raw_text)
    norm_value = norm_match.group(1).upper() if norm_match else None
    dimension_value = dim_match.group(0) if dim_match else None
    nominal_dn = int(dn_match.group(1).replace(".", "")) if dn_match else None
    if existing.nominal_diameter_dn is not None and nominal_dn is None:
        nominal_dn = existing.nominal_diameter_dn
    if existing.load_class and load_class is None:
        load_class = existing.load_class
    if existing.norm and norm_value is None:
        norm_value = existing.norm
    if existing.dimensions and dimension_value is None:
        dimension_value = existing.dimensions

    if category == "Kanalrohre":
        detected_norm = norm_match.group(1).upper() if norm_match else None
        if material in {"Beton", "Stahlbeton"} or detected_norm == "DIN EN 1916":
            subcategory = "Betonrohre"

    install_area = None
    if "fahrbahn" in text:
        install_area = "Fahrbahn"
    elif "gehweg" in text:
        install_area = "Gehweg"
    elif "erdeinbau" in text or "kanal" in text:
        install_area = "Erdeinbau"

    reference = None
    for candidate in ("ACO PowerDrain", "ACO Multiline", "FASERFIX", "RECYFIX", "GEFAguard", "Multitop", "KG 2000", "ACO", "Wavin", "Ostendorf"):
        if candidate.lower() in text:
            reference = candidate
            break
    if existing.reference_product and reference is None:
        reference = existing.reference_product

    # Pipe length extraction
    pipe_length_mm = None
    length_match = PIPE_LENGTH_RE.search(position.raw_text)
    if length_match:
        val = int(length_match.group(1))
        unit_str = length_match.group(2).lower()
        pipe_length_mm = val if unit_str == "mm" else val * 1000

    # Angle extraction (for fittings: "45°", "30 Grad")
    angle_deg = None
    angle_match = ANGLE_RE.search(position.raw_text)
    if angle_match:
        angle_deg = int(angle_match.group(1))

    # Application area
    application_area = None
    for kw, area_val in APPLICATION_KEYWORDS.items():
        if kw in text:
            application_area = area_val
            break

    system_family = _infer_system_family(text)
    if system_family is None and reference:
        system_family = _infer_system_family(reference.lower())
    connection_type = _infer_connection_type(text)
    seal_type = _infer_seal_type(text)
    compatible_systems = _infer_compatible_systems(text)
    secondary_dn = _infer_secondary_dn(text, category, subcategory)
    if existing.secondary_nominal_diameter_dn is not None and secondary_dn is None:
        secondary_dn = existing.secondary_nominal_diameter_dn
    if existing.system_family and system_family is None:
        system_family = existing.system_family
    if existing.connection_type and connection_type is None:
        connection_type = existing.connection_type
    if existing.seal_type and seal_type is None:
        seal_type = existing.seal_type
    if existing.compatible_systems and compatible_systems is None:
        compatible_systems = existing.compatible_systems
    if existing.installation_area and install_area is None:
        install_area = existing.installation_area
    if existing.application_area and application_area is None:
        application_area = existing.application_area
    if existing.pipe_length_mm is not None and pipe_length_mm is None:
        pipe_length_mm = existing.pipe_length_mm
    if existing.angle_deg is not None and angle_deg is None:
        angle_deg = existing.angle_deg
    components = _infer_components(
        position,
        category=category,
        subcategory=subcategory,
        material=material,
        nominal_dn=_infer_structure_dn(text, nominal_dn) if category == "Schachtbauteile" else nominal_dn,
        secondary_dn=secondary_dn,
        load_class=load_class,
        dimensions=dimension_value,
        system_family=system_family,
        installation_area=install_area,
        connection_type=connection_type,
    )

    # For shaft positions, prefer the structure DN as the main DN
    if category == "Schachtbauteile":
        structure_dn = _infer_structure_dn(text, nominal_dn)
        if structure_dn is not None:
            nominal_dn = structure_dn

    sortiment_relevant: bool | None = None
    if is_service_position:
        sortiment_relevant = False
    elif category in {
        "Kanalrohre",
        "Schachtabdeckungen",
        "Schachtbauteile",
        "Formstücke",
        "Straßenentwässerung",
        "Rinnen",
        "Dichtungen & Zubehör",
        "Geotextilien",
    }:
        sortiment_relevant = True
    elif any(keyword in text for keyword in NON_CATALOG_KEYWORDS):
        sortiment_relevant = False

    return TechnicalParameters(
        product_category=category,
        product_subcategory=subcategory,
        material=material,
        nominal_diameter_dn=nominal_dn,
        secondary_nominal_diameter_dn=secondary_dn,
        load_class=load_class,
        norm=norm_value,
        dimensions=dimension_value,
        quantity=position.quantity,
        unit=position.unit,
        reference_product=reference,
        installation_area=install_area,
        pipe_length_mm=pipe_length_mm,
        angle_deg=angle_deg,
        application_area=application_area,
        system_family=system_family,
        connection_type=connection_type,
        seal_type=seal_type,
        compatible_systems=compatible_systems,
        components=components,
        sortiment_relevant=sortiment_relevant,
    )


# Materials that never carry an SN (stiffness) class
_NO_SN_MATERIALS = {"Beton", "Stahlbeton", "Polymerbeton", "Gusseisen", "Stahl"}


# Canonical category names — lookup is done case-insensitively
_CANONICAL_CATEGORIES: dict[str, str] = {
    "kanalrohre": "Kanalrohre",
    "schachtabdeckungen": "Schachtabdeckungen",
    "schachtbauteile": "Schachtbauteile",
    "formstuecke": "Formstücke",
    "formstücke": "Formstücke",
    "strassenentwässerung": "Straßenentwässerung",
    "straßenentwässerung": "Straßenentwässerung",
    "strassenentwaesserung": "Straßenentwässerung",
    "rinnen": "Rinnen",
    "dichtungen & zubehoer": "Dichtungen & Zubehör",
    "dichtungen & zubehör": "Dichtungen & Zubehör",
    "dichtungen & zubehor": "Dichtungen & Zubehör",
    "geotextilien": "Geotextilien",
    "gasrohre": "Gasrohre",
    "wasserrohre": "Wasserrohre",
    "druckrohre": "Druckrohre",
    "kabelschutz": "Kabelschutz",
}


def _post_merge_sanity(params: TechnicalParameters, position: LVPosition) -> TechnicalParameters:
    """Fix contradictions that arise from LLM/heuristic merge."""
    text = f"{position.description}\n{position.raw_text}".lower()
    updates: dict[str, Any] = {}

    # 0) Normalize category spelling (LLM sometimes returns ASCII transliterations or wrong case)
    if params.product_category:
        canonical = _CANONICAL_CATEGORIES.get(params.product_category.lower())
        if canonical and canonical != params.product_category:
            updates["product_category"] = canonical

    # 1a) SN value from text takes precedence over title-extracted SN.
    #     Priority: "Material: PP SNxx" line > last "PP SNxx" mention > title SN.
    #     LV titles sometimes say "SN16" while the spec block says "PP SN10".
    _MATERIAL_SN_RE = re.compile(r"material[:\s]+\w+\s+sn\s*(\d+)", re.IGNORECASE)
    _STANDALONE_SN_RE = re.compile(r"\bpp\s+sn\s*(\d+)", re.IGNORECASE)
    mat_sn_match = _MATERIAL_SN_RE.search(text)
    if not mat_sn_match:
        # Fallback: find all "PP SNxx" patterns; use the last one (most specific)
        all_sn_matches = list(_STANDALONE_SN_RE.finditer(text))
        mat_sn_match = all_sn_matches[-1] if all_sn_matches else None
    if mat_sn_match and params.stiffness_class_sn is not None:
        spec_sn = int(mat_sn_match.group(1))
        if spec_sn != params.stiffness_class_sn:
            logger.info("Overriding SN %d→%d for %s (text SN is authoritative)",
                         params.stiffness_class_sn, spec_sn, position.ordnungszahl)
            updates["stiffness_class_sn"] = spec_sn

    # 1b) Beton/Stahlbeton products never have SN classes
    if params.material in _NO_SN_MATERIALS and params.stiffness_class_sn is not None:
        logger.info("Clearing SN=%s for %s position %s (material=%s)",
                     params.stiffness_class_sn, params.product_category, position.ordnungszahl, params.material)
        updates["stiffness_class_sn"] = None

    # 2) If text explicitly says "beton" but merged material is PP/PVC/HDPE, trust the text
    #    EXCEPT when the product itself is explicitly PVC/PP (e.g. Sanierungsstutzen "in Betonrohre"
    #    — "Betonrohr" describes the TARGET pipe, not the product material)
    _CONCRETE_KEYWORDS = ("betonfertigteil", "betonschacht", "betonrohr", "beton,")
    _PRODUCT_MATERIAL_MARKERS = (r"\bpvc-u\b", r"\bpvc-kg\b", r"\bpolyvinylchlorid\b")
    # Products that are always plastic — "Betonrohr" in text is always the TARGET pipe
    _ALWAYS_PLASTIC_PRODUCTS = ("sanierungsstutzen", "reparaturstutzen")
    if any(kw in text for kw in _CONCRETE_KEYWORDS):
        if params.material in ("PP", "PVC-U", "HDPE", "PE 100", "PE 100 RC"):
            # Don't override if the text explicitly names PVC-U or the product is inherently plastic
            product_is_plastic = (
                any(re.search(m, text) for m in _PRODUCT_MATERIAL_MARKERS)
                or any(kw in text for kw in _ALWAYS_PLASTIC_PRODUCTS)
            )
            if not product_is_plastic:
                logger.info("Overriding material %s→Beton for position %s (text says concrete)",
                             params.material, position.ordnungszahl)
                updates["material"] = "Beton"

    # 3) Straßenablauf: extract dimensions from "500/300mm" pattern
    if params.product_category == "Straßenentwässerung":
        dim_in_text = re.search(r"(\d{3,4})\s*/\s*(\d{3,4})\s*mm", text)
        if dim_in_text and params.dimensions is None:
            updates["dimensions"] = dim_in_text.group(0)
        # "Aufsatz" positions inherit DN from parent Straßenablauf, but it's the outlet DN, not product DN
        if "aufsatz" in text and params.nominal_diameter_dn and "abfluss" not in text:
            logger.info("Clearing inherited DN=%s for Straßenablauf-Aufsatz %s",
                         params.nominal_diameter_dn, position.ordnungszahl)
            updates["nominal_diameter_dn"] = None

    # 4) Products that are NOT drainage Rinnen but got categorized as such by LLM
    _NOT_DRAINAGE_RINNE_SANITY = ("muldenrinne", "bordsteinrinne", "pendelrinne")
    # Also catch non-drainage products misclassified as Rinnen (Pflaster, Randsteine, Betonplatten, etc.)
    _NOT_RINNE_PRODUCTS = (
        "randstein", "kantenstein", "wegebekantung", "tiefbord",
        "pflasterstein", "betonsteinpflaster", "betonpflaster", "sickerpflaster", "verbundpflaster",
        "plattenband", "betonplatten", "betonplattenband",
        "hochbord",
    )
    if params.product_category == "Rinnen":
        is_false_rinne = (
            any(kw in text for kw in _NOT_DRAINAGE_RINNE_SANITY)
            or any(kw in text for kw in _NOT_RINNE_PRODUCTS)
        )
        if is_false_rinne:
            logger.info("Clearing false Rinnen category for %s (found non-drainage product keyword)", position.ordnungszahl)
            updates["product_category"] = None
            updates["product_subcategory"] = None

    # 4b) LLM sometimes categorizes Schacht positions as "Kanalrohre" because the
    #     text mentions DN sizes. Reclassify when text clearly says "Schacht".
    _SCHACHT_KEYWORDS = ("sammelschacht", "kontrollschacht", "revisionsschacht", "kontroll- und sammelschacht")
    if params.product_category == "Kanalrohre" and any(kw in text for kw in _SCHACHT_KEYWORDS):
        logger.info("Reclassifying %s from Kanalrohre→Schachtbauteile (text says Schacht)", position.ordnungszahl)
        updates["product_category"] = "Schachtbauteile"
        updates["product_subcategory"] = None

    # 5) DL positions should not carry DN (LLM often picks up irrelevant dimensions)
    if position.position_type == "dienstleistung" and params.nominal_diameter_dn is not None:
        logger.info("Clearing DN=%s for DL position %s", params.nominal_diameter_dn, position.ordnungszahl)
        updates["nominal_diameter_dn"] = None

    # 5) Normalize load_class — remove spaces (e.g. "B 125" → "B125")
    if params.load_class and " " in params.load_class:
        normalized_load = params.load_class.replace(" ", "")
        logger.info("Normalizing load_class '%s'→'%s' for %s", params.load_class, normalized_load, position.ordnungszahl)
        updates["load_class"] = normalized_load

    # 5b) Articles that never have a DN (Mauerscheiben, Bordsteine, Stützwände, Pflaster, Blockstufen).
    #     Heuristic DN_RE often matches DN from Nebenpositionen (e.g. Drainagerohr DN 100 as
    #     Unterposition of a Mauerscheibe) and wrongly assigns it to the main article.
    _NO_DN_ARTICLE_TYPES = (
        "mauerscheibe", "mauerscheiben-ecke", "stützwand", "stuetzwand",
        "winkelstein", "l-stein", "bordstein", "randstein", "pflasterstein",
        "blockstufe", "rinnenstein", "absenkstein", "kurvenstein",
    )
    article_lower = (params.article_type or "").lower()
    if article_lower and any(t in article_lower for t in _NO_DN_ARTICLE_TYPES):
        if params.nominal_diameter_dn is not None:
            logger.info("Clearing DN=%s for %s (article type has no nominal diameter)",
                         params.nominal_diameter_dn, position.ordnungszahl)
            updates["nominal_diameter_dn"] = None
        if params.secondary_nominal_diameter_dn is not None:
            updates["secondary_nominal_diameter_dn"] = None

    # 5c) secondary_dn must differ from primary_dn.
    #     Also catch DA/DN confusion: PVC DN 100 ↔ DA 110, DN 150 ↔ DA 160, DN 200 ↔ DA 200
    #     (common rounded DA values just above the DN). When the LV gives a single
    #     connection size that matches primary_dn via the DA mapping, secondary stays null.
    current_primary = updates.get("nominal_diameter_dn", params.nominal_diameter_dn)
    current_secondary = updates.get("secondary_nominal_diameter_dn", params.secondary_nominal_diameter_dn)
    if current_primary is not None and current_secondary is not None:
        _DN_TO_DA = {100: 110, 125: 140, 150: 160, 200: 200, 250: 250, 300: 315}
        same_size = (
            current_primary == current_secondary
            or _DN_TO_DA.get(current_primary) == current_secondary
        )
        if same_size:
            logger.info("Clearing secondary DN=%s (same size as primary DN=%s) for %s",
                         current_secondary, current_primary, position.ordnungszahl)
            updates["secondary_nominal_diameter_dn"] = None

    # 5d) Prefer explicit "Norm: X" label over first regex match.
    #     Avoids picking up compatibility-system norms like "DIN 19534" for Rohrklappen.
    _NORM_LABEL_RE = re.compile(
        r"norm[:\s]+((?:DIN|EN|ISO)(?:\s+EN)?(?:\s+ISO)?[\s]*\d+(?:-\d+)?(?:\s+Typ\s+\d+)?)",
        re.IGNORECASE,
    )
    norm_label_match = _NORM_LABEL_RE.search(position.raw_text or "")
    if norm_label_match:
        preferred_norm = norm_label_match.group(1).strip()
        # Normalize whitespace
        preferred_norm = re.sub(r"\s+", " ", preferred_norm)
        if params.norm != preferred_norm:
            logger.info("Overriding norm %r → %r for %s (explicit 'Norm:' label)",
                         params.norm, preferred_norm, position.ordnungszahl)
            updates["norm"] = preferred_norm

    # 5d-2) Preserve llm_parser's literal material output when it was generic ("Kunststoff").
    #       The llm_parser prompt explicitly forbids inferring PP/PVC/PE from generic "Kunststoff";
    #       heuristic keyword matching and the second Gemini batch would otherwise overwrite it.
    original_material = (position.parameters.material or "").strip()
    if original_material.lower() == "kunststoff" and params.material in {"PP", "PVC-U", "HDPE", "PE 100", "PE 100 RC"}:
        logger.info("Reverting material %s → 'Kunststoff' for %s (llm_parser chose literal Kunststoff)",
                     params.material, position.ordnungszahl)
        updates["material"] = "Kunststoff"

    # 5e) Clear system_family when the text only mentions it in a compatibility context
    #     (e.g. Rohrklappe "zum Anschluss für PVC-KG-Rohr" — KG is not the family of the
    #     Klappe itself, it's what the Klappe connects to).
    if params.system_family:
        lower_raw = (position.raw_text or "").lower()
        klappe_article = article_lower and ("klappe" in article_lower or "schieber" in article_lower)
        compat_marker_present = any(m in lower_raw for m in _SYSTEM_FAMILY_COMPAT_MARKERS)
        if klappe_article and compat_marker_present and params.system_family in {"KG PVC-U", "KG 2000", "HDPE"}:
            logger.info("Clearing system_family=%s for %s (compatibility-only reference)",
                         params.system_family, position.ordnungszahl)
            updates["system_family"] = None

    # 6) Clear fabricated pipe materials — LLM sometimes assigns PP/PVC-U/HDPE to non-pipe products
    #    like Noppenschutzbahn, Auslaufstücke, etc. where the PDF doesn't specify material
    _PIPE_MATERIALS = {"PP", "PVC-U", "HDPE", "PE 100", "PE 100 RC"}
    _MATERIAL_TEXT_MARKERS = {
        "PP": (r"\bpp\b",),
        "PVC-U": (r"\bpvc\b", r"\bpvc-u\b"),
        "HDPE": (r"\bhdpe\b", r"\bpe-hd\b", r"\bpe\s*100\b"),
        "PE 100": (r"\bpe\s*100\b", r"\bpe-hd\b"),
        "PE 100 RC": (r"\bpe\s*100\b", r"\brc\b"),
    }
    if params.material in _PIPE_MATERIALS and any(kw in text for kw in NON_CATALOG_KEYWORDS):
        markers = _MATERIAL_TEXT_MARKERS.get(params.material, ())
        mat_in_text = any(re.search(m, text, re.IGNORECASE) for m in markers)
        if not mat_in_text:
            logger.info("Clearing fabricated material %s for non-catalog position %s", params.material, position.ordnungszahl)
            updates["material"] = None

    if updates:
        return params.model_copy(update=updates)
    return params


def _maybe_reclassify_as_dl(position: LVPosition, params: TechnicalParameters) -> LVPosition:
    """Reclassify a material position as DL if heuristics detect it's clearly a service."""
    # position_type can be None (regex parser) or "material" (LLM parser)
    if position.position_type not in ("material", None):
        return position
    if position.position_type == "dienstleistung":
        return position

    # Use only the TITLE (first line of description) for reclassification
    # to avoid false positives from keywords in context text
    title = (position.description or "").split(",")[0].split("\n")[0].lower().strip()
    full_text = f"{position.description}\n{position.raw_text}".lower()

    # Positions with DN or load class have a strong product signal — don't reclassify
    if DN_RE.search(position.raw_text or ""):
        return position
    if any(lc.lower() in full_text for lc in LOAD_CLASSES):
        return position

    should_reclassify = False

    # "Zulage" = price surcharge for labor, not a standalone product
    if re.match(r"^\s*zulage\b", title):
        should_reclassify = True

    # Service keywords that override — checked against TITLE only
    _SERVICE_TITLE_KEYWORDS = (
        "kopfloch", "anschlussarbeiten",
        "schnittkanten", "schnitt ausklinkung",
        "regulieren",
        "plattendruckversuch", "lastplattendruck", "druckversuch",
        "tragschicht",
        "fertiggarage",
    )
    if any(kw in title for kw in _SERVICE_TITLE_KEYWORDS):
        should_reclassify = True

    if should_reclassify:
        logger.info("Reclassifying %s→DL by heuristic (text: '%s')", position.ordnungszahl, position.description[:60])
        return position.model_copy(update={
            "position_type": "dienstleistung",
            "billable": False,
        })
    return position


def _maybe_reclassify_as_material(position: LVPosition) -> LVPosition:
    """Override DL→material when the text clearly indicates material supply (liefern)
    and not just 'bauseits' (client-supplied). Fixes false DL from LLM."""
    if position.position_type != "dienstleistung":
        return position

    text = f"{position.description}\n{position.raw_text}".lower()

    # If material is provided by the client ("bauseits"), keep as DL
    if "bauseits" in text or "beistellung" in text:
        return position

    # Strong product keywords: always a material product, trigger with "liefern" OR "herstellen"
    _STRONG_PRODUCT_KEYWORDS = (
        "dränmatte", "draenmatte", "dränschicht", "draenschicht",
        "geotextil", "vlies",
        "noppenbahn", "schutzlage",
    )
    # Weak product keywords: can be objects of construction work,
    # only trigger with explicit "liefern" (not "herstellen" which is ambiguous)
    _WEAK_PRODUCT_KEYWORDS = (
        "pflaster", "verbundpflaster", "verbundsteinpflaster",
        "randstein", "bordstein", "kantenstein", "tiefbord",
        "betonplatten", "plattenband",
    )

    has_liefern = "liefern" in text
    has_herstellen = "herstellen" in text
    has_verlegen = "verlegen" in text
    has_strong = any(kw in text for kw in _STRONG_PRODUCT_KEYWORDS)
    has_weak = any(kw in text for kw in _WEAK_PRODUCT_KEYWORDS)

    # Strong product keywords are ALWAYS material products — any installation verb suffices
    # Weak product keywords can be objects of construction work — only "liefern" is safe
    should_reclassify = (
        (has_strong and (has_liefern or has_herstellen or has_verlegen))
        or (has_weak and has_liefern)
    )

    if should_reclassify:
        logger.info("Reclassifying %s DL→material (product keyword + supply verb)", position.ordnungszahl)
        return position.model_copy(update={
            "position_type": "material",
            "billable": True,
        })

    return position


def enrich_positions_with_parameters(positions: list[LVPosition]) -> list[LVPosition]:
    """Heuristic-only enrichment for the regex-fallback path.

    The main LLM path parses the PDF directly and does not use this function.
    Here we only run heuristic inference + sanity normalization as a best-effort
    when Gemini is unavailable or returned no positions.
    """
    enriched: list[LVPosition] = []
    for position in positions:
        interpreted = _infer_with_heuristics(position)
        position = _maybe_reclassify_as_dl(position, interpreted)
        position = _maybe_reclassify_as_material(position)
        interpreted = _post_merge_sanity(interpreted, position)
        enriched.append(position.model_copy(update={"parameters": interpreted}))
    return enriched
