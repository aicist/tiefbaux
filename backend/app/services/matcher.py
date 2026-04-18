from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ManualOverride, Product
from ..schemas import ComponentRequirement, LVPosition, ProductSuggestion, ScoreBreakdown, TechnicalParameters

LOAD_RANK = {
    "A15": 1,
    "B125": 2,
    "C250": 3,
    "D400": 4,
    "E600": 5,
    "F900": 6,
}

# DN equivalences: in practice DN100 = DN110 (OD 110mm), DN150 = DN160 (OD 160mm)
# Extended for PE pressure pipes where DN differs from OD
DN_EQUIVALENTS: dict[int, set[int]] = {
    100: {110},
    110: {100},
    150: {160},
    160: {150},
    200: {225},
    225: {200},
    250: {280},
    280: {250},
    300: {315},
    315: {300},
    400: {450},
    450: {400},
}

# Product type keywords for subcategory matching
PRODUCT_TYPE_KEYWORDS: dict[str, list[str]] = {
    "rohr": ["rohr", "kanalleitung", "entwässerungskanalleitung"],
    "bogen": ["bogen", "bögen", "krümmer"],
    "abzweig": ["abzweig", "abzweige", "t-stück"],
    "muffe": ["muffe", "doppelmuffe", "überschiebmuffe"],
    "reduzierstück": ["reduzierstück", "reduktion"],
    "uebergangsstueck": ["übergangsstück", "uebergangsstueck", "übergang"],
    "passstueck": ["passstück", "passstueck"],
    "revisionsstück": ["revisionsstück", "revisionsstueck", "reinigungsrohr", "revisionsrohr", "revisionselement", "revisionsaufsatz"],
    "anschluss": ["anschluss", "anschlussteil", "anschlussstück"],
    "sanierungsstutzen": ["sanierungsstutzen", "reparaturstutzen"],
    "rohrkupplung": ["rohrkupplung", "vpc-rohrkupplung"],
    "rueckstauverschluss": ["rückstau", "rueckstau", "froschklappe", "rohrklappe", "klappe"],
    "absperrschieber": ["absperrschieber", "schieber"],
    "revisionsschacht": ["revisionsschacht", "revischacht", "entwässerungsschacht", "entwaesserungsschacht", "kontrollschacht"],
    "kabelschacht": ["kabelschacht"],
    "laternenhuelse": ["laternenhuelse", "laternenhülse"],
    "schachtring": ["schachtring", "schachtringe"],
    "schachtboden": ["schachtboden", "schachtunterteil"],
    "schachtrohr": ["schachtrohr"],
    "schachtfutter": ["schachtfutter"],
    "konus": ["konus", "schachthals", "schachtkonus"],
    "ausgleichsring": ["ausgleichsring", "auflagering"],
    "abdeckung": ["abdeckung", "deckel", "abdeckplatte", "wannenschachtabdeckung"],
    "rost": ["rost", "gitterrost", "gussrost", "stegrost", "schlitzabdeckung", "laengsstabrost", "längsstabrost"],
    "schmutzfangeimer": ["schmutzfangeimer", "schmutzeimer", "laubfang", "schmutzfang", "eimer"],
    "stirnwand": ["stirnwand", "kombistirnwand", "abschlussdeckel", "anfangsdeckel", "enddeckel", "rinnenende"],
    "einlaufkasten": ["einlaufkasten", "anschlusskasten", "sinkkasten", "schlammfangkasten", "punkteinlauf", "sinkkastenunterteil"],
    "ablauf": ["ablauf", "straßenablauf", "hofablauf", "einlauf"],
    "rinne": ["rinne", "entwässerungsrinne", "schwerlastrinne", "powerdrain", "multiline"],
    "auslauf": ["auslauf", "auslaufstück"],
    "dichtung": ["dichtung", "dichtungsring", "lippendichtring", "profilring", "gleitringdichtung", "mengering"],
    "kappe": ["muffenstopfen", "kappe", "stopfen"],
    "zubehoer": ["zubehör", "zubehoer", "rinnenzubehör", "rinnenzubehoer", "lastaufnahmering", "steigleiter", "schmutzfänger", "schmutzfaenger", "schlitzrahmen"],
}

SUBCATEGORY_TYPE_HINTS: dict[str, str] = {
    "kg-rohre": "rohr",
    "pp-rohre": "rohr",
    "x-stream rohre": "rohr",
    "betonrohre": "rohr",
    "pe-druckrohr": "rohr",
    "kabelschutzrohre": "rohr",
    "rohre": "rohr",
    "kg-boegen": "bogen",
    "rohrbogen": "bogen",
    "x-stream boegen": "bogen",
    "pp-bogen": "bogen",
    "pe-bogen": "bogen",
    "kabelschutzrohrbogen": "bogen",
    "kg-abzweige": "abzweig",
    "abzweig": "abzweig",
    "pp-abzweig": "abzweig",
    "kg-reduzierstuecke": "reduzierstück",
    "reduzierstück": "reduzierstück",
    "reduktionsstueck": "reduzierstück",
    "reduktion": "reduzierstück",
    "uebergangsstueck": "uebergangsstueck",
    "übergangsstück": "uebergangsstueck",
    "passstueck": "passstueck",
    "passstück": "passstueck",
    "muffe": "muffe",
    "reinigungsrohr": "revisionsstück",
    "revisionsstueck": "revisionsstück",
    "revisionsstück": "revisionsstück",
    "revisionselement": "revisionsstück",
    "revisionsaufsatz": "revisionsstück",
    "universal-doppelmuffe": "muffe",
    "universal-ueberschiebmuffe": "muffe",
    "universalmuffenstopfen": "kappe",
    "kg-anschluss": "anschluss",
    "anschluss-stueck": "anschluss",
    "anschlussset": "anschluss",
    "anschlussadapter": "anschluss",
    "anschlussplatte": "anschluss",
    "rueckstauverschluss": "rueckstauverschluss",
    "rueckstausicherung": "rueckstauverschluss",
    "absperrarmaturen": "absperrschieber",
    "revisionsschacht": "revisionsschacht",
    "kabelschacht": "kabelschacht",
    "laternenhuelse": "laternenhuelse",
    "laternenhülse": "laternenhuelse",
    "schachtringe": "schachtring",
    "schachtring": "schachtring",
    "schachtunterteil": "schachtboden",
    "tegra schachtboden": "schachtboden",
    "sx 400 schachtboden": "schachtboden",
    "schachtboden": "schachtboden",
    "betonschacht": "revisionsschacht",
    "kunststoffschacht": "revisionsschacht",
    "schachtrohr": "schachtrohr",
    "schachtfutter": "schachtfutter",
    "tegra schachtrohr": "schachtrohr",
    "schachtrohrverlaengerung": "schachtrohr",
    "schachthals/konus": "konus",
    "tegra schachtkonus": "konus",
    "schaftkonus": "konus",
    "ausgleichsring": "ausgleichsring",
    "auflagering": "ausgleichsring",
    "abdeckung": "abdeckung",
    "abdeckungen": "rost",
    "rost": "rost",
    "rinnenrost": "rost",
    "schmutzfangeimer": "schmutzfangeimer",
    "schachtabdeckung": "abdeckung",
    "tegra schachtabdeckung": "abdeckung",
    "wannenschachtabdeckung": "abdeckung",
    "teleskopabdeckung": "abdeckung",
    "betonabdeckplatte": "abdeckung",
    "stirnwand": "stirnwand",
    "stirnwaende": "stirnwand",
    "stirnwände": "stirnwand",
    "punkteinlaeufe": "einlaufkasten",
    "punkteinläufe": "einlaufkasten",
    "einlaufkasten": "einlaufkasten",
    "sinkkasten": "einlaufkasten",
    "hofablauf": "einlaufkasten",
    "strassenablauf": "ablauf",
    "strassenablauf zubehoer": "zubehoer",
    "entwaesserungsrinne": "rinne",
    "linienentwaesserung": "rinne",
    "linienentwässerung": "rinne",
    "schwerlastrinne": "rinne",
    "dichtungen & zubehoer": "dichtung",
    "dichtung": "dichtung",
    "zubehoer": "zubehoer",
    "bohrhilfe": "zubehoer",
    "bohrer": "zubehoer",
}

STRICT_POSITION_TYPES = {
    "rohr",
    "bogen",
    "abzweig",
    "muffe",
    "reduzierstück",
    "uebergangsstueck",
    "passstueck",
    "revisionsstück",
    "anschluss",
    "rueckstauverschluss",
    "absperrschieber",
    "revisionsschacht",
    "kabelschacht",
    "laternenhuelse",
    "schachtring",
    "schachtboden",
    "schachtrohr",
    "schachtfutter",
    "konus",
    "ausgleichsring",
    "abdeckung",
    "rost",
    "schmutzfangeimer",
    "stirnwand",
    "einlaufkasten",
    "ablauf",
    "rinne",
    "dichtung",
    "kappe",
}

SERVICE_HINTS = (
    "abbruch",
    "entsorgung",
    "demont",
    "stundenlohn",
    "vorhaltung",
    "baustellen",
    "sperrung",
    "rueckbau",
    "rückbau",
    "abbauen",
    "transport",
    "verdichten",
    "einmessen",
)

# Keywords that indicate the position is NOT a product from our catalog.
# Used to reject LLM mis-classifications (e.g. "Asphalt" → "Straßenentwässerung").
NON_PRODUCT_HINTS = (
    "asphalt",
    "bitumen",
    "beton einbau",
    "estrich",
    "pflaster",
    "bordstein",
    "fugenmörtel",
    "kabeltrassenband",
    "trassenwarnband",
    "sand 0/",
    "sand 0-",
    "schotter",
    "schottertragschicht",
    "kies ",
    "oberboden",
    "rasen ansäen",
    "rasen ansaeen",
    "rinnenplatte",
    "naturstein",
    "fuge in bit",
    "gussasphalt",
    "ersatzboden",
    "tiefbordstein",
    "betonpflaster",
    "plattenbelag",
    "hydrant",
    "anbohrschelle",
    "einbaugarnitur",
    "hauseinführung",
    "hauseinfuehrung",
    "zählereinrichtung",
    "zaehlereinrichtung",
    "verbindungsleit",
    "notversorgungsleitung",
    # Nicht im Baustoff-Sortiment
    "stützmauer",
    "stuetzmauer",
    "poller",
    "blockstufe",
    "rasenkantenstein",
    "leitplanke",
    "schutzplanke",
    "rigole",
    "rigolenkörper",
    "rigolenkoerper",
    "muldenrinne",
    "fundament",
    "zaun",
    "zaunpfosten",
    "beleuchtung",
    "laterne",
    "geländer",
    "gelaender",
    "baumschutz",
    "baumwurzel",
    "wurzelschutz",
    # Bau/Bewehrung
    "bewehrung",
    "bewehrungsstahl",
    "stahlmatte",
    "transportbeton",
    "ortbeton",
    "betonmischung",
    # Verfüllung/Bettung
    "grabenverfuellung",
    "grabenverfüllung",
    "rohrbettung",
    "filterkies",
    "sickerschicht",
    "filterschicht",
    # Verkehr
    "fahrbahnmarkierung",
    "absperrpfosten",
    "verkehrszeichen",
    # Prüfung/Inspektion (Dienstleistung)
    "druckpruefung",
    "druckprüfung",
    "druckprobe",
    "dichtheitspruefung",
    "dichtheitsprüfung",
    "kamerabefahrung",
    "tv-untersuchung",
    # Mechanisch/individuell gefertigt
    "pumpenschacht",
    "schieberschacht",
    # Spezialwerkzeug (Fremdprodukte)
    "montagewerkzeug",
)

MODIFIER_HINTS = (
    "zulage zu vorgenannten",
    "zulage zu vorstehenden",
    "zulage zu vorhergehenden",
    "zur ausfuehrung mit",
    "zur ausführung mit",
)


_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
})


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().translate(_UMLAUT_MAP)


def _subcategory_product_type(category: str | None, subcategory: str | None) -> str | None:
    sub = _normalize(subcategory)
    cat = _normalize(category)

    if sub in SUBCATEGORY_TYPE_HINTS:
        return SUBCATEGORY_TYPE_HINTS[sub]

    for hint, product_type in SUBCATEGORY_TYPE_HINTS.items():
        if hint in sub:
            return product_type

    if cat in {"kanalrohre", "druckrohre", "gasrohre", "wasserrohre", "kabelschutz"} and "rohr" in sub:
        return "rohr"
    if cat == "rinnen" and not sub:
        return "rinne"
    if cat == "schachtabdeckungen" and not sub:
        return "abdeckung"

    return None


def _guess_category(position: LVPosition) -> tuple[str | None, str | None]:
    params = position.parameters
    if params.product_category:
        return params.product_category, params.product_subcategory

    text = f"{position.description} {position.raw_text}".lower()

    # Use OZ prefix to detect domain for pipe positions
    oz = (position.ordnungszahl or "").strip()
    is_pipe = re.search(r"\brohr\b", text) and re.search(r"\bdn\s*\d", text)
    is_druckrohr = "druckrohr" in text or "druckleitung" in text or "pe\s*100" in text or "pe-hd" in text
    if is_pipe or is_druckrohr:
        if oz.startswith("25"):
            return "Gasrohre", None
        if oz.startswith("30"):
            return "Wasserrohre", None
        if oz.startswith("35"):
            return "Kabelschutz", None
        if is_druckrohr:
            # Generic pressure pipe — let matcher try all pressure categories
            return "Druckrohre", None
        return "Kanalrohre", "KG-Rohre"
    if re.search(r"\bkg\b", text) and re.search(r"\bdn\b", text):
        return "Kanalrohre", "KG-Rohre"
    if re.search(r"\brueckstau\b|\brückstau\b|\bfroschklappe\b|\brohrklappe\b", text):
        return "Formstücke", "Rückstauverschluss"
    if re.search(r"\babsperrschieber\b", text):
        return "Formstücke", "Absperrarmaturen"
    if re.search(r"\bschacht\b", text) and re.search(r"\babdeckung\b", text):
        return "Schachtabdeckungen", None
    if re.search(r"\bschachtunterteil\b", text):
        return "Schachtbauteile", "Schachtunterteil"
    if re.search(r"\bschachtring\b", text):
        return "Schachtbauteile", "Schachtring"
    if re.search(r"\bkonus\b|\bschachthals\b", text):
        return "Schachtbauteile", "Schachthals/Konus"
    if re.search(r"\bschacht\b", text):
        return "Schachtbauteile", None
    if re.search(r"\bstraßenablauf\b|\bstrassenablauf\b", text):
        return "Straßenentwässerung", "Straßenablauf"
    if re.search(r"\brinne\b", text) and not re.search(r"\bmuldenrinne\b", text):
        return "Rinnen", None
    if re.search(r"\bbogen\b|\babzweig\b|\bmuffe\b", text):
        return "Formstücke", None
    if re.search(r"\bdichtung\b", text):
        return "Dichtungen & Zubehör", None
    return None, None


def _extract_tokens(text: str) -> set[str]:
    tokens = set(re.findall(r"[a-zA-Z0-9äöüÄÖÜß-]{3,}", text.lower()))
    stop_words = {
        "und", "oder", "mit", "ohne", "der", "die", "das",
        "ein", "eine", "für", "von", "auf", "inkl", "einschl",
        "nach", "gem", "bzw", "bis", "aus",
    }
    return {token for token in tokens if token not in stop_words}


def _detect_product_type(text: str, category: str | None = None, subcategory: str | None = None) -> str | None:
    """Detect what type of product is described (rohr, bogen, abzweig, etc.).

    Uses a priority system: specific types (bogen, abzweig, muffe, konus, ...)
    are checked first.  Generic "rohr" is only returned when no more specific
    type matches.  This prevents "Formteil (Bögen) zu KG-Rohr DN200" from
    being classified as "rohr".
    """
    lower = _normalize(text)

    if "muffenstopfen" in lower:
        return "kappe"

    if "schlitzrahmen" in lower:
        return "zubehoer"

    subcategory_type = _subcategory_product_type(category, subcategory)
    if subcategory_type and subcategory_type != "zubehoer":
        # Don't let generic subcategory ("KG-Rohre") override when the text
        # clearly identifies a more specific product type (e.g. "Bögen").
        if subcategory_type == "rohr":
            for kw in PRODUCT_TYPE_KEYWORDS.get("bogen", []):
                if _normalize(kw) in lower:
                    return "bogen"
            for kw in PRODUCT_TYPE_KEYWORDS.get("abzweig", []):
                if _normalize(kw) in lower:
                    return "abzweig"
        return subcategory_type

    # Full channel positions often mention the grate as an included part.
    # Keep the main article type on "rinne" unless the text clearly asks for
    # a specific accessory/component instead.
    if lower.startswith(("einlaufkasten", "anschlusskasten", "sinkkasten", "schlammfangkasten")):
        return "einlaufkasten"

    if "schlitzrahmen" in lower:
        return "zubehoer"

    if "rinnenzubehoer" in lower or "rinnenzubehör" in lower:
        return "zubehoer"

    if "rinne" in lower and not any(
        token in lower
        for token in ("stirnwand", "enddeckel", "anfangsdeckel", "abschlussdeckel", "einlaufkasten", "sinkkasten")
    ):
        return "rinne"

    if _normalize(category) in {"kanalrohre", "druckrohre", "gasrohre", "wasserrohre", "kabelschutz"}:
        if any(token in lower for token in ("rohr", "rohren", "kanal", "leerrohr")) and not any(
            token in lower
            for token in (
                "formstueck",
                "bogen",
                "boegen",
                "abzweig",
                "stopfen",
                "reinigungsrohr",
                "revisions",
                "anschluss",
                "schachtfutter",
                "sanierungsstutzen",
                "rohrkupplung",
            )
        ):
            return "rohr"

    # Accessories often reference the main product family in the text ("für Einlaufkasten"),
    # but should still stay accessories instead of being promoted to full product types.
    if lower.startswith(("schmutzfangeimer", "laubfang", "knebel", "arretierung", "verbinder", "leerrohre", "gehrungsschnitt")):
        return "zubehoer"

    # High-priority: check specific product types first
    priority_types = [
        "absperrschieber", "rueckstauverschluss", "anschluss", "sanierungsstutzen", "rohrkupplung", "revisionsschacht", "kabelschacht", "laternenhuelse", "schachtring",
        "revisionsstück", "ausgleichsring", "rost", "schmutzfangeimer", "einlaufkasten", "stirnwand",
        "bogen", "abzweig", "schachtfutter", "muffe", "uebergangsstueck", "passstueck", "reduzierstück", "konus",
        "schachtboden", "schachtrohr", "abdeckung", "ablauf", "rinne",
        "auslauf", "dichtung", "kappe", "zubehoer",
    ]
    for ptype in priority_types:
        for kw in PRODUCT_TYPE_KEYWORDS[ptype]:
            if _normalize(kw) in lower:
                return ptype

    # Low-priority: generic "rohr"
    for kw in PRODUCT_TYPE_KEYWORDS["rohr"]:
        if _normalize(kw) in lower:
            return "rohr"

    return None


def _is_modifier_position(position: LVPosition, position_product_type: str | None) -> bool:
    lower_text = _normalize(f"{position.description} {position.raw_text}")
    if not any(hint in lower_text for hint in MODIFIER_HINTS):
        return False

    # If the text still identifies a concrete standalone article type, keep matching enabled.
    if position_product_type in {
        "abdeckung",
        "stirnwand",
        "einlaufkasten",
        "ausgleichsring",
        "revisionsstück",
        "schachtring",
        "schachtboden",
        "schachtrohr",
        "konus",
    }:
        return False

    return True


def _product_type_score(position_type: str | None, product: Product) -> tuple[float, list[str]]:
    """Score how well the product type matches what the LV position describes."""
    if not position_type:
        return 0.0, []

    product_text = f"{product.artikelname} {product.artikelbeschreibung or ''} {product.unterkategorie or ''}"
    product_type = _detect_product_type(product_text, product.kategorie, product.unterkategorie)

    if not product_type:
        return 0.0, []

    if position_type == product_type:
        return 15.0, [f"Produkttyp passt ({position_type})"]

    # Some types are closely related
    related = {
        ("rohr", "muffe"): -5.0,
        ("bogen", "abzweig"): -5.0,
        ("schachtboden", "schachtrohr"): 0.0,
        ("schachtrohr", "konus"): 0.0,
        ("anschluss", "muffe"): -5.0,
        ("einlaufkasten", "ablauf"): -4.0,
        ("stirnwand", "abdeckung"): -4.0,
    }
    pair = (position_type, product_type)
    reverse_pair = (product_type, position_type)
    if pair in related:
        return related[pair], [f"Produkttyp ähnlich ({product_type})"]
    if reverse_pair in related:
        return related[reverse_pair], [f"Produkttyp ähnlich ({product_type})"]

    # Clear mismatch: LV says "Rohr" but product is "Abzweig" etc.
    return -20.0, [f"Produkttyp falsch ({position_type} ≠ {product_type})"]


def _material_family(value: str | None) -> str:
    text = _normalize(value)
    if not text:
        return ""
    # Generic "Kunststoff" → no family (compatible with everything)
    if text == "kunststoff":
        return ""
    if "stahlbeton" in text or "faserbeton" in text or text == "beton" or "beton" in text:
        return "beton"
    if "pvc" in text:
        return "pvc"
    if text in ("pp", "pp-hm", "ppmd") or "polypropylen" in text:
        return "pp"
    if text.startswith("pe") or "hdpe" in text:
        return "pe"
    if "edelstahl" in text:
        return "stahl"
    if text in ("stahl", "verzinkter stahl"):
        return "stahl"
    if "aluminium" in text:
        return "aluminium"
    if text in ("gusseisen", "guss"):
        return "guss"
    if text in ("sbr", "epdm", "nbr"):
        return "elastomer"
    if text in ("steinzeug",):
        return "steinzeug"
    return text


def _system_families_compatible(required: str | None, product_system: str | None) -> bool:
    required_norm = _normalize(required)
    product_norm = _normalize(product_system)
    if not required_norm or not product_norm:
        return False
    if required_norm == product_norm or required_norm in product_norm or product_norm in required_norm:
        return True

    alias_groups = [
        # PP gravity pipe systems with compatible steckmuffe connections
        {"kg 2000", "green connect 2000", "pp sn10 gruen", "pp sn10",
         "wavin green connect 2000", "awadukt pp", "awadukt hpp", "rehau awadukt hpp"},
        {"wavin xs", "wavin sx 400", "wavin xs 400"},
        {"wavin acaro pp", "acaro pp"},
    ]
    for group in alias_groups:
        if any(alias in required_norm for alias in group) and any(alias in product_norm for alias in group):
            return True
    return False


def _has_hard_conflict(
    position: LVPosition,
    category: str | None,
    subcategory: str | None,
    position_product_type: str | None,
    product: Product,
) -> bool:
    product_text = f"{product.artikelname} {product.artikelbeschreibung or ''} {product.unterkategorie or ''}"
    product_type = _detect_product_type(product_text, product.kategorie, product.unterkategorie)
    expected_type = position_product_type or _subcategory_product_type(category, subcategory)
    position_subcategory_type = _subcategory_product_type(category, subcategory)

    # Certain specialized product types must match exactly; otherwise no suggestion.
    strict_types = {
        "rohr",
        "bogen",
        "abzweig",
        "muffe",
        "reduzierstück",
        "uebergangsstueck",
        "passstueck",
        "revisionsstück",
        "kappe",
        "anschluss",
        "sanierungsstutzen",
        "rohrkupplung",
        "absperrschieber",
        "rueckstauverschluss",
        "revisionsschacht",
        "kabelschacht",
        "laternenhuelse",
        "schachtring",
        "schachtfutter",
        "ausgleichsring",
        "rost",
        "schmutzfangeimer",
        "einlaufkasten",
        "ablauf",
        "rinne",
        "stirnwand",
    }
    if expected_type in strict_types and product_type != expected_type:
        return True

    # When the parsed LV subcategory already identifies a concrete product family,
    # reject accessories and different fitting families instead of trying to rank them.
    # Skip this check when expected_type (text-based) overrode the subcategory type,
    # e.g. position says "Bögen" but subcategory is "KG-Rohre" → expected_type=bogen wins.
    if position_subcategory_type in STRICT_POSITION_TYPES and product_type != position_subcategory_type:
        if expected_type == position_subcategory_type:
            return True

    # Concrete pipe systems (e.g. DIN EN 1916 / Betonrohre) are not interchangeable with PP/PVC pipes.
    required_material = _material_family(position.parameters.material)
    product_material = _material_family(product.werkstoff)
    required_norm = _normalize(position.parameters.norm)
    product_norm = _normalize(product.norm_primaer)
    category_norm = _normalize(category)
    required_secondary_dn = position.parameters.secondary_nominal_diameter_dn
    product_secondary_dns = _parse_compatible_dns(product.kompatible_dn_anschluss)
    extracted_secondary_dn = _extract_secondary_dn_from_product(product)
    required_systems = _normalize_system_values(position.parameters.compatible_systems)
    product_systems = _product_compatible_systems(product)

    if category_norm == "kanalrohre":
        if required_material == "beton" and product_material and product_material != "beton":
            return True
        if "1916" in required_norm and product_norm and "1916" not in product_norm:
            return True

    # Installation/testing norms describe how to lay/test pipes, not the pipe itself.
    # They must not cause a hard conflict with product norms.
    _INSTALLATION_NORM_IDS = {"1610", "18318", "18186", "18134", "1053"}
    is_installation_norm = any(n in required_norm for n in _INSTALLATION_NORM_IDS) if required_norm else False

    # PP/PVC Kanalrohr product-norm families — any two of these are treated as the
    # same rohr class (homogen, strukturiert, PP-MD, PVC-U), so a cross-family match
    # is a score penalty, not a hard reject.
    _KANAL_NORM_IDS = ("1401", "1852", "13476", "14758", "1437", "12666")

    if expected_type == "rohr" and required_material in {"beton", "pvc", "pp", "pe"}:
        if product_material and product_material != required_material:
            return True
        if required_norm and product_norm and not is_installation_norm and "9969" not in required_norm and required_norm not in product_norm and product_norm not in required_norm:
            both_kanal = (
                any(n in required_norm for n in _KANAL_NORM_IDS)
                and any(n in product_norm for n in _KANAL_NORM_IDS)
            )
            if not both_kanal:
                return True
        required_area = _normalize(position.parameters.application_area)
        product_area = _normalize(product.einsatzbereich)
        if required_area and product_area and required_area not in product_area and product_area not in required_area:
            return True

    # Schachtfutter are elastomer-sealed connectors — the outer shell material (PP
    # or PVC-U) is interchangeable as long as the seal fits the DN. Keep them out
    # of the strict material-match list.
    if expected_type in {"bogen", "abzweig", "reduzierstück", "revisionsstück", "muffe", "anschluss"} and required_material in {"beton", "pvc", "pp", "pe"}:
        if product_material and product_material != required_material:
            return True

    if expected_type in {"ablauf", "einlaufkasten", "schachtboden", "schachtring", "konus", "ausgleichsring"} and required_material == "beton":
        if "beton" not in product_material and "beton" not in _normalize(product_text):
            return True

    # Schachtringe must remain Schachtringe, not generic accessories.
    if expected_type == "schachtring" and "schachtring" not in _normalize(product_text):
        return True
    if expected_type == "schachtring":
        position_text = _normalize(f"{position.description} {position.raw_text}")
        product_text_norm = _normalize(product_text)
        if "ohne steigeisen" in position_text and "mit steigeisen" in product_text_norm:
            return True
        if "mit steigeisen" in position_text and "ohne steigeisen" in product_text_norm:
            return True

    required_system_family = _normalize(position.parameters.system_family)
    product_system_family = _normalize(product.system_familie)
    if not product_system_family:
        product_system_family = _normalize(product_text)

    if required_system_family:
        strict_system_types = {
            "rohr",
            "bogen",
            "abzweig",
            "muffe",
            "reduzierstück",
            "revisionsstück",
            "anschluss",
            "schachtboden",
            "schachtrohr",
            "schachtfutter",
            "konus",
            "ausgleichsring",
            "rost",
            "schmutzfangeimer",
            "stirnwand",
            "einlaufkasten",
        }
        if expected_type in strict_system_types:
            if not _system_families_compatible(required_system_family, product_system_family):
                # When position has a reference_product ("z.B. ..."), the system_family
                # is a hint, not a hard requirement. Only reject if the product is from
                # a truly incompatible system (e.g. pressure vs gravity pipe).
                # Otherwise let scoring handle preference.
                if position.parameters.reference_product:
                    pass  # soft preference — handled by _system_family_score()
                else:
                    return True

    if required_secondary_dn is not None and expected_type in {"anschluss", "abzweig", "reduzierstück", "rueckstauverschluss", "absperrschieber"}:
        product_main_dn, product_branch_dn = _extract_dn_pair_from_product(product)
        if product_branch_dn is not None:
            valid_branch_dns = {product_branch_dn, *DN_EQUIVALENTS.get(product_branch_dn, set())}
            if required_secondary_dn not in valid_branch_dns:
                return True
            if position.parameters.nominal_diameter_dn is not None and product_main_dn is not None:
                valid_main_dns = {product_main_dn, *DN_EQUIVALENTS.get(product_main_dn, set())}
                if position.parameters.nominal_diameter_dn not in valid_main_dns:
                    return True
        if product_secondary_dns or extracted_secondary_dn is not None:
            valid_dns = set(product_secondary_dns)
            if extracted_secondary_dn is not None:
                valid_dns.add(extracted_secondary_dn)
            valid_dns.update(*(DN_EQUIVALENTS.get(dn, set()) for dn in list(valid_dns)))
            if required_secondary_dn not in valid_dns:
                return True

    strict_dn_types = {"rohr", "bogen", "muffe", "revisionsstück", "kappe", "laternenhuelse", "einlaufkasten", "rost", "schachtboden", "schachtrohr", "schachtfutter", "konus", "ablauf", "rinne"}
    if position.parameters.nominal_diameter_dn is not None and expected_type in strict_dn_types:
        valid_dns = {position.parameters.nominal_diameter_dn, *DN_EQUIVALENTS.get(position.parameters.nominal_diameter_dn, set())}
        product_dn = product.nennweite_dn
        product_od = product.nennweite_od
        if product_dn is not None and product_dn not in valid_dns:
            return True
        if product_dn is None and product_od is not None and product_od not in valid_dns:
            return True

    if required_systems and expected_type in {"anschluss", "rueckstauverschluss", "absperrschieber"}:
        if product_systems and required_systems.isdisjoint(product_systems):
            return True

    # Rückstau-/Froschklappen and Absperrschieber need exact functional match.
    lower_text = _normalize(f"{position.description} {position.raw_text}")
    if ("froschklappe" in lower_text or "rueckstau" in lower_text or "rückstau" in lower_text) and product_type != "rueckstauverschluss":
        return True
    if "absperrschieber" in lower_text and product_type != "absperrschieber":
        return True

    # ── Full assembly positions must not match accessories/sets ──
    _ASSEMBLY_TYPES = {"revisionsschacht", "schachtboden", "ablauf", "einlaufkasten", "rinne"}
    _ACCESSORY_TYPES = {"anschluss", "zubehoer", "dichtung", "muffe", "kappe", "rost", "stirnwand", "schmutzfangeimer"}
    if expected_type in _ASSEMBLY_TYPES and product_type in _ACCESSORY_TYPES:
        return True
    if expected_type == "rinne" and product_type == "einlaufkasten":
        return True
    # Also reject if product subcategory is clearly an accessory for assembly positions
    prod_subcat = _normalize(product.unterkategorie or "")
    if expected_type in _ASSEMBLY_TYPES and any(hint in prod_subcat for hint in ("anschlussset", "zubehoer", "zubehör", "adapter", "dichtung")):
        return True

    # ── Pressure pipe vs gravity pipe hard conflict ──
    _PRESSURE_CATEGORIES = {"druckrohre", "gasrohre", "wasserrohre"}
    _GRAVITY_CATEGORIES = {"kanalrohre"}
    pos_cat_norm = _normalize(position.parameters.product_category)
    prod_cat_norm = _normalize(product.kategorie)
    if pos_cat_norm in _PRESSURE_CATEGORIES and prod_cat_norm in _GRAVITY_CATEGORIES:
        return True
    if pos_cat_norm in _GRAVITY_CATEGORIES and prod_cat_norm in _PRESSURE_CATEGORIES:
        return True

    # ── Universal material hard conflict ──
    # Schachtfutter connect a pipe to a manhole wall via an elastomer seal; the
    # seal's DN decides compatibility, not the shell material. Skip the hard
    # reject so PVC-U Schachtfutter remain candidates for a PP pipe request.
    req_fam = _material_family(position.parameters.material)
    prod_fam = _material_family(product.werkstoff)
    if expected_type != "schachtfutter" and req_fam and prod_fam and req_fam != prod_fam:
        return True
    # Steinzeug/Guss positions: products without werkstoff are definitely not
    # Steinzeug or Guss — reject rather than letting them slip through.
    if req_fam in ("steinzeug", "guss") and not prod_fam:
        return True

    # ── SN under-spec hard conflict (safety-critical) ──
    # Allow one SN tier below the spec (e.g. SN12 when SN16 requested) — the
    # scoring layer penalises it clearly. Reject only if the product sits two
    # or more tiers below the requirement.
    required_sn = position.parameters.stiffness_class_sn
    if required_sn is not None:
        sn_str = (product.steifigkeitsklasse_sn or "").strip()
        sn_match = re.search(r"(\d+)", sn_str)
        if sn_match:
            ladder = [2, 4, 8, 10, 12, 16]
            product_sn = int(sn_match.group(1))
            try:
                req_idx = ladder.index(required_sn)
                prod_idx = ladder.index(product_sn) if product_sn in ladder else -1
            except ValueError:
                req_idx = prod_idx = -1
            if req_idx >= 0 and prod_idx >= 0:
                if prod_idx < req_idx - 1:
                    return True
            elif product_sn < required_sn:
                # Non-standard SN values fall back to strict under-spec reject.
                return True

    # ── Load class under-spec hard conflict (safety-critical) ──
    required_load = position.parameters.load_class
    if required_load:
        req_rank = LOAD_RANK.get(required_load.upper().replace(" ", ""))
        prod_class = (product.belastungsklasse or "").upper().replace(" ", "")
        prod_rank = LOAD_RANK.get(prod_class)
        if req_rank and prod_rank and prod_rank < req_rank:
            return True

    # ── Angle hard conflict for bends ──
    if expected_type == "bogen" and position.parameters.angle_deg is not None:
        product_text = _normalize(f"{product.artikelname} {product.artikelbeschreibung or ''}")
        angle_match = re.search(r"(\d+)\s*(?:grad|°)", product_text)
        if angle_match:
            product_angle = int(angle_match.group(1))
            if product_angle != position.parameters.angle_deg:
                return True

    return False


def _parse_compatible_dns(value: str | None) -> set[int]:
    if not value:
        return set()
    dns: set[int] = set()
    for piece in value.split(","):
        piece = piece.strip()
        if not piece:
            continue
        if piece.isdigit():
            dns.add(int(piece))
    return dns


def _extract_secondary_dn_from_product(product: Product) -> int | None:
    text = f"{product.artikelname} {product.artikelbeschreibung or ''}"
    slash_match = re.search(r"\bDN/?(?:OD)?\s*(\d{2,4})\s*[/x]\s*(?:(?:DN/?(?:OD)?|OD)\s*)?(\d{2,4})\b", text, re.IGNORECASE)
    if slash_match:
        return int(slash_match.group(2))
    return None


def _extract_dn_pair_from_product(product: Product) -> tuple[int | None, int | None]:
    text = f"{product.artikelname} {product.artikelbeschreibung or ''}"
    slash_match = re.search(r"\bDN/?(?:OD)?\s*(\d{2,4})\s*[/x]\s*(?:(?:DN/?(?:OD)?|OD)\s*)?(\d{2,4})\b", text, re.IGNORECASE)
    if slash_match:
        return int(slash_match.group(1)), int(slash_match.group(2))
    return product.nennweite_dn, _extract_secondary_dn_from_product(product)


def _normalize_system_values(values: list[str] | None) -> set[str]:
    if not values:
        return set()

    normalized: set[str] = set()
    for value in values:
        text = _normalize(value)
        if not text:
            continue
        normalized.add(text)
        if "kg" in text:
            normalized.add("kg")
        if "ht" in text:
            normalized.add("ht")
        if "pvc" in text:
            normalized.add("pvc-kg")
        if "pe-hd" in text or text == "pe":
            normalized.add("pe-hd")
        if "guss" in text:
            normalized.add("gussrohr")
        if "beton" in text:
            normalized.add("betonrohr")
        if "steinzeug" in text:
            normalized.add("steinzeug")
    return normalized


def _product_compatible_systems(product: Product) -> set[str]:
    systems: list[str] = []
    if product.kompatible_systeme:
        systems.extend(piece.strip() for piece in re.split(r"[,;/]", product.kompatible_systeme) if piece.strip())

    text = _normalize(f"{product.artikelname} {product.artikelbeschreibung or ''}")
    keyword_map = {
        "ht": "HT",
        "kg": "KG",
        "pvc-kg": "PVC-KG",
        "pe-hd": "PE-HD",
        "gussrohr": "Gussrohr",
        "betonrohr": "Betonrohr",
        "steinzeug": "Steinzeug",
    }
    for keyword, label in keyword_map.items():
        if keyword in text:
            systems.append(label)
    return _normalize_system_values(systems)


def _product_connection_type(product: Product) -> str | None:
    explicit = _normalize(product.verbindungstyp)
    if explicit:
        return explicit
    text = _normalize(f"{product.artikelname} {product.artikelbeschreibung or ''}")
    if "steckmuffe" in text:
        return "steckmuffe"
    if "doppelmuffe" in text:
        return "doppelmuffe"
    if "ueberschiebmuffe" in text:
        return "ueberschiebmuffe"
    if "flansch" in text:
        return "flansch"
    if "spitzende" in text:
        return "spitzende"
    if "muffe" in text:
        return "muffe"
    return None


def _product_seal_type(product: Product) -> str | None:
    explicit = _normalize(product.dichtungstyp)
    if explicit:
        return explicit
    text = _normalize(f"{product.artikelname} {product.artikelbeschreibung or ''}")
    if "gleitringdichtung" in text:
        return "gleitringdichtung"
    if "lippendichtung" in text:
        return "lippendichtung"
    if "profildichtung" in text or "profilring" in text:
        return "profildichtung"
    if "doppeldichtung" in text:
        return "doppeldichtung"
    return None


def _extract_height_mm(text: str | None) -> int | None:
    lower = _normalize(text)
    if not lower:
        return None

    match = re.search(r"\bh\s*=?\s*(\d+)\s*mm\b", lower)
    if match:
        return int(match.group(1))

    match = re.search(r"\bstaerke\s*(\d+)\s*cm\b", lower)
    if match:
        return int(match.group(1)) * 10

    match = re.search(r"\bh\s*=?\s*(\d+)\b", lower)
    if match:
        value = int(match.group(1))
        return value if value >= 20 else value * 10

    return None


def _price_for_quantity(product: Product, quantity: float) -> float | None:
    if product.vk_listenpreis_netto is None:
        return None

    if quantity >= 100 and product.staffelpreis_ab_100 is not None:
        return product.staffelpreis_ab_100
    if quantity >= 50 and product.staffelpreis_ab_50 is not None:
        return product.staffelpreis_ab_50
    if quantity >= 10 and product.staffelpreis_ab_10 is not None:
        return product.staffelpreis_ab_10
    return product.vk_listenpreis_netto


def _text_similarity_score(position_tokens: set[str], product: Product) -> float:
    product_text = f"{product.artikelname} {product.artikelbeschreibung or ''} {product.unterkategorie or ''}"
    product_tokens = _extract_tokens(product_text)
    if not position_tokens or not product_tokens:
        return 0.0
    overlap = position_tokens.intersection(product_tokens)
    return min((len(overlap) / max(1, len(position_tokens))) * 20, 12.0)


def _minimum_score(position: LVPosition, category: str | None, position_product_type: str | None) -> float:
    min_score = 42.0 if category else 50.0
    if position_product_type in {"absperrschieber", "rueckstauverschluss", "revisionsschacht", "schachtring", "schachtboden", "abdeckung", "revisionsstück", "ausgleichsring", "rost", "schmutzfangeimer", "einlaufkasten", "stirnwand"}:
        min_score += 10.0
    technical_constraints = sum(
        1
        for value in (
            position.parameters.nominal_diameter_dn,
            position.parameters.load_class,
            position.parameters.material,
            position.parameters.norm,
            position.parameters.stiffness_class_sn,
            position.parameters.dimensions,
            position.parameters.pipe_length_mm,
            position.parameters.angle_deg,
            position.parameters.application_area,
            position.parameters.secondary_nominal_diameter_dn,
            position.parameters.system_family,
            position.parameters.connection_type,
            position.parameters.seal_type,
            tuple(position.parameters.compatible_systems or []),
        )
        if value not in (None, "")
    )
    if technical_constraints >= 4:
        min_score += 6.0
    return min_score


# Related pressure pipe categories — partial match when categories differ
_RELATED_CATEGORIES: dict[str, set[str]] = {
    "gasrohre": {"druckrohre"},
    "wasserrohre": {"druckrohre"},
    "druckrohre": {"gasrohre", "wasserrohre"},
    "rinnen": {"strassenentwasserung"},
    "strassenentwasserung": {"rinnen"},
}


def _category_match_score(category: str | None, subcategory: str | None, product: Product) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []

    category_norm = _normalize(category)
    subcategory_norm = _normalize(subcategory)
    product_category = _normalize(product.kategorie)
    product_subcategory = _normalize(product.unterkategorie)

    if category_norm and category_norm == product_category:
        score += 25
        reasons.append(f"Kategorie passt ({product.kategorie})")
    elif category_norm and (category_norm in product_category or product_category in category_norm):
        score += 15
        reasons.append("Kategorie ähnlich")
    elif category_norm and product_category in _RELATED_CATEGORIES.get(category_norm, set()):
        score += 15
        reasons.append(f"Kategorie verwandt ({product.kategorie})")
    elif category_norm and category_norm == product_subcategory:
        # LV sagt oft nur "Formstücke" als Kategorie, Katalog trägt es als
        # Unterkategorie unter "Kanalrohre/Formstücke". Teilpunkte vergeben.
        score += 15
        reasons.append(f"Kategorie als Unterkategorie ({product.unterkategorie})")

    if subcategory_norm and subcategory_norm == product_subcategory:
        score += 18
        reasons.append(f"Unterkategorie passt ({product.unterkategorie})")
    elif subcategory_norm and (subcategory_norm in product_subcategory or product_subcategory in subcategory_norm):
        score += 10
        reasons.append("Unterkategorie ähnlich")

    return score, reasons


def _dn_score(required_dn: int | None, product: Product) -> tuple[float, list[str]]:
    if required_dn is None:
        return 0.0, []

    reasons: list[str] = []

    # Try to extract DN from description if product has no nennweite_dn
    product_dn = product.nennweite_dn
    if product_dn is None and product.artikelbeschreibung:
        dn_match = re.search(r"DN/?(?:OD)?\s*(\d+)", product.artikelbeschreibung)
        if dn_match:
            product_dn = int(dn_match.group(1))

    # Also check OD for PE pressure pipes (LV often uses "DN 110" meaning OD 110)
    product_od = product.nennweite_od

    if product_dn == required_dn:
        reasons.append(f"DN {required_dn} exakt")
        return 25.0, reasons

    # Match against OD (PE-Druckrohre use OD, not DN)
    if product_od == required_dn:
        reasons.append(f"OD {required_dn} exakt")
        return 25.0, reasons

    # Check DN equivalences (e.g. DN100 ↔ DN110)
    equivalent_dns = DN_EQUIVALENTS.get(required_dn, set())
    if product_dn in equivalent_dns:
        reasons.append(f"DN {required_dn}≈{product_dn} (äquivalent)")
        return 22.0, reasons
    if product_od in equivalent_dns:
        reasons.append(f"OD {product_od}≈DN {required_dn} (äquivalent)")
        return 22.0, reasons

    compatible_dns = _parse_compatible_dns(product.kompatible_dn_anschluss)
    if required_dn in compatible_dns:
        reasons.append(f"DN {required_dn} kompatibel")
        return 16.0, reasons

    # Check equivalents in compatible list too
    for eq_dn in equivalent_dns:
        if eq_dn in compatible_dns:
            reasons.append(f"DN {required_dn}≈{eq_dn} kompatibel")
            return 14.0, reasons

    # Product has no DN or OD info at all — don't penalize, just no bonus
    if product_dn is None and product_od is None:
        return 0.0, []

    return -15.0, [f"DN weicht ab ({product_dn or product_od} ≠ {required_dn})"]


def _secondary_dn_score(required_dn: int | None, product: Product) -> tuple[float, list[str]]:
    if required_dn is None:
        return 0.0, []

    compatible_dns = _parse_compatible_dns(product.kompatible_dn_anschluss)
    _, product_secondary_dn = _extract_dn_pair_from_product(product)

    if required_dn in compatible_dns or product_secondary_dn == required_dn:
        return 18.0, [f"Anschluss-DN {required_dn} passt"]

    equivalent_dns = DN_EQUIVALENTS.get(required_dn, set())
    if compatible_dns.intersection(equivalent_dns):
        eq = sorted(compatible_dns.intersection(equivalent_dns))[0]
        return 14.0, [f"Anschluss-DN {required_dn}≈{eq}"]
    if product_secondary_dn in equivalent_dns:
        return 14.0, [f"Anschluss-DN {required_dn}≈{product_secondary_dn}"]

    if compatible_dns or product_secondary_dn is not None:
        actual = product_secondary_dn if product_secondary_dn is not None else ",".join(str(v) for v in sorted(compatible_dns))
        return -18.0, [f"Anschluss-DN abweichend ({actual} ≠ {required_dn})"]

    return 0.0, []


def _load_class_score(required: str | None, product: Product) -> tuple[float, list[str]]:
    if not required:
        return 0.0, []

    required_rank = LOAD_RANK.get(required.upper().replace(" ", ""))
    product_class = (product.belastungsklasse or "").upper().replace(" ", "")
    product_rank = LOAD_RANK.get(product_class)

    if required_rank is None or product_rank is None:
        return 0.0, []

    if product_rank < required_rank:
        return -25.0, [f"Belastungsklasse {product_class} unter {required}"]
    if product_rank == required_rank:
        return 18.0, [f"Belastungsklasse {product_class} passend"]

    return 12.0, [f"Belastungsklasse {product_class} über Anforderung"]


def _material_score(required_material: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_material:
        return 0.0, []

    required = _normalize(required_material)
    product_material = _normalize(product.werkstoff)

    if not product_material:
        return 0.0, []

    req_fam = _material_family(required_material)
    prod_fam = _material_family(product.werkstoff)

    if req_fam and prod_fam and req_fam == prod_fam:
        return 15.0, [f"Werkstoff passt ({product.werkstoff})"]
    if required and (required in product_material or product_material in required):
        return 15.0, [f"Werkstoff passt ({product.werkstoff})"]

    # Mismatch is handled by hard conflict; remaining case is partial/unknown
    return 0.0, []


def _norm_base(norm: str) -> str:
    # Strip trailing "-<digits>" part suffix (DIN EN 1852-1 -> DIN EN 1852) and
    # any amendment letters so that "DIN EN 13476-2:2018-08" and "DIN EN 13476"
    # collapse onto a shared base for matching purposes.
    base = re.split(r"[:+]", norm, maxsplit=1)[0]
    base = re.sub(r"-\d+[a-z]?$", "", base).strip()
    return _normalize(base)


def _norm_score(required_norm: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_norm:
        return 0.0, []

    required = _normalize(required_norm)
    product_norm = _normalize(product.norm_primaer)

    if not product_norm:
        return 0.0, []

    if required and required in product_norm:
        return 12.0, [f"Norm passt ({product.norm_primaer})"]

    # Accept part-number differences on the same base norm: DIN EN 1852-1
    # (LV) vs DIN EN 1852 (product) should match — same family, just the
    # part suffix not tracked on the product record.
    req_base = _norm_base(required_norm)
    prod_base = _norm_base(product.norm_primaer or "")
    if req_base and prod_base and (req_base == prod_base or req_base in prod_base or prod_base in req_base):
        return 10.0, [f"Norm passt ({product.norm_primaer})"]

    # Cross-family PP/PVC Kanalrohr norms (1401/1852/13476/14758/1437/12666) are
    # all valid for Abwasserkanal — soften the penalty so Reinigungsrohre and
    # andere Kanal-Formstücke aus einer Nachbar-Normfamilie noch ranken können.
    kanal_ids = ("1401", "1852", "13476", "14758", "1437", "12666")
    if any(n in required for n in kanal_ids) and any(n in product_norm for n in kanal_ids):
        return -5.0, [f"Norm-Familie abweichend ({product.norm_primaer} ≠ {required_norm})"]

    # Norm explicitly specified but product has a different norm
    return -15.0, [f"Norm abweichend ({product.norm_primaer} ≠ {required_norm})"]


def _sn_score(required_sn: int | None, product: Product) -> tuple[float, list[str]]:
    if required_sn is None:
        return 0.0, []

    product_sn_str = (product.steifigkeitsklasse_sn or "").strip()
    if not product_sn_str:
        # Position requires SN but product has no SN data — likely not suitable
        return -15.0, [f"Keine SN-Angabe (SN{required_sn} gefordert)"]

    # Extract numeric SN value (e.g. "SN8" -> 8, "8" -> 8)
    sn_match = re.search(r"(\d+)", product_sn_str)
    if not sn_match:
        return -15.0, [f"SN nicht lesbar (SN{required_sn} gefordert)"]

    product_sn = int(sn_match.group(1))

    if product_sn == required_sn:
        return 18.0, [f"SN{required_sn} exakt"]
    if product_sn > required_sn:
        return 10.0, [f"SN{product_sn} über Anforderung (SN{required_sn})"]

    # Product SN below spec. One tier below (e.g. SN12 vs SN16) is surfaced
    # with a penalty so the user sees it flagged; more than one tier below is
    # already hard-rejected by _has_hard_conflict.
    ladder = [2, 4, 8, 10, 12, 16]
    if required_sn in ladder and product_sn in ladder:
        if ladder.index(required_sn) - ladder.index(product_sn) == 1:
            return -12.0, [f"SN{product_sn} unter Anforderung (SN{required_sn} gefordert)"]
    return -30.0, [f"SN{product_sn} unter Anforderung (SN{required_sn})"]


def _pipe_length_score(required_mm: int | None, product: Product) -> tuple[float, list[str]]:
    """Score based on pipe length match."""
    if required_mm is None:
        return 0.0, []
    product_len = product.laenge_mm
    if not product_len:
        return 0.0, []
    if product_len == required_mm:
        return 8.0, [f"Baulänge {required_mm}mm exakt"]
    # Close match (within 20%)
    ratio = product_len / required_mm
    if 0.8 <= ratio <= 1.2:
        return 3.0, [f"Baulänge ähnlich ({product_len}mm ≈ {required_mm}mm)"]
    return -5.0, [f"Baulänge abweichend ({product_len}mm ≠ {required_mm}mm)"]


def _angle_score(required_deg: int | None, product: Product) -> tuple[float, list[str]]:
    """Score based on fitting angle match (e.g. 45° Bogen)."""
    if required_deg is None:
        return 0.0, []
    product_text = f"{product.artikelname} {product.artikelbeschreibung or ''}"
    angle_match = re.search(r"(\d+)\s*(?:°|[Gg]rad)", product_text, re.IGNORECASE)
    if not angle_match:
        return 0.0, []
    product_angle = int(angle_match.group(1))
    if product_angle == required_deg:
        return 10.0, [f"Winkel {required_deg}° exakt"]
    return -15.0, [f"Winkel abweichend ({product_angle}° ≠ {required_deg}°)"]


def _application_area_score(required_area: str | None, product: Product) -> tuple[float, list[str]]:
    """Score based on application area match (Trinkwasser, Gas, Abwasser)."""
    if not required_area:
        return 0.0, []
    product_area = (product.einsatzbereich or "").lower()
    if not product_area:
        return 0.0, []
    required_lower = required_area.lower()
    if required_lower in product_area or product_area in required_lower:
        return 8.0, [f"Einsatzbereich passt ({product.einsatzbereich})"]
    return -10.0, [f"Einsatzbereich abweichend ({product.einsatzbereich} ≠ {required_area})"]


def _height_score(position: LVPosition, position_product_type: str | None, product: Product) -> tuple[float, list[str]]:
    if position_product_type not in {"schachtring", "ausgleichsring"}:
        return 0.0, []

    required_height = _extract_height_mm(f"{position.description} {position.raw_text}")
    if required_height is None:
        return 0.0, []

    product_height = product.hoehe_mm or _extract_height_mm(f"{product.artikelname} {product.artikelbeschreibung or ''}")
    if product_height is None:
        return 0.0, []

    if product_height == required_height:
        return 10.0, [f"Höhe {required_height} mm passt"]

    return -10.0, [f"Höhe abweichend ({product_height} mm ≠ {required_height} mm)"]


def _system_family_score(required_system_family: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_system_family:
        return 0.0, []

    required = _normalize(required_system_family)
    product_system = _normalize(product.system_familie)
    if not product_system:
        product_system = _normalize(f"{product.artikelname} {product.artikelbeschreibung or ''}")

    if not product_system:
        return 0.0, []

    if _system_families_compatible(required, product_system):
        return 12.0, [f"Systemfamilie passt ({product.system_familie or required_system_family})"]
    return -10.0, [f"Systemfamilie abweichend ({product.system_familie or '-'} ≠ {required_system_family})"]


def _connection_type_score(required_connection_type: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_connection_type:
        return 0.0, []

    required = _normalize(required_connection_type)
    product_connection = _product_connection_type(product)
    if not product_connection:
        return 0.0, []

    if required == product_connection or required in product_connection or product_connection in required:
        return 9.0, [f"Anschlussart passt ({product.verbindungstyp or product_connection})"]
    return -10.0, [f"Anschlussart abweichend ({product.verbindungstyp or product_connection} ≠ {required_connection_type})"]


def _seal_type_score(required_seal_type: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_seal_type:
        return 0.0, []

    required = _normalize(required_seal_type)
    product_seal = _product_seal_type(product)
    if not product_seal:
        return 0.0, []

    if required == product_seal or required in product_seal or product_seal in required:
        return 8.0, [f"Dichtung passt ({product.dichtungstyp or product_seal})"]
    return -8.0, [f"Dichtung abweichend ({product.dichtungstyp or product_seal} ≠ {required_seal_type})"]


def _compatible_systems_score(required_systems: list[str] | None, product: Product) -> tuple[float, list[str]]:
    required = _normalize_system_values(required_systems)
    if not required:
        return 0.0, []

    product_systems = _product_compatible_systems(product)
    if not product_systems:
        return 0.0, []

    overlap = required.intersection(product_systems)
    if overlap:
        return 10.0, [f"Systemkompatibel ({', '.join(sorted(overlap))})"]
    return -12.0, [f"Systeme abweichend ({', '.join(required_systems)})"]


def _parse_dimensions(dim_str: str | None) -> tuple[int, ...]:
    """Extract numeric dimensions from a string like '300/500', '500x500', '300x300mm'.

    Filters out numbers that look like DN values or load class designations to
    avoid contaminating dimension comparisons.
    """
    if not dim_str:
        return ()
    # Remove DN, OD, SN references and load class designations before extracting
    cleaned = re.sub(r"\bDN/?(?:OD)?\s*\d+", "", dim_str, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b[A-F]\d{2,3}\b", "", cleaned)  # load classes like D400
    cleaned = re.sub(r"\bSN\s*\d+", "", cleaned, flags=re.IGNORECASE)
    nums = re.findall(r"(\d+)", cleaned)
    return tuple(sorted(int(n) for n in nums if int(n) > 1))


def _dimensions_score(required_dims: str | None, product: Product) -> tuple[float, list[str]]:
    """Score based on dimension match (e.g. aufsatz frame size 300x500)."""
    req = _parse_dimensions(required_dims)
    if not req:
        return 0.0, []

    # Check product name and description for matching dimensions
    product_text = f"{product.artikelname or ''} {product.artikelbeschreibung or ''}"
    prod_dims = _parse_dimensions(product_text)

    if not prod_dims:
        # Also try laenge/breite from product columns
        col_dims = tuple(sorted(
            d for d in [product.laenge_mm, product.breite_mm] if d and d > 0
        ))
        if col_dims:
            prod_dims = col_dims

    if not prod_dims:
        return 0.0, []

    if req == prod_dims:
        return 15.0, [f"Abmessungen {required_dims} exakt"]
    # Check if at least the key dimensions overlap
    if set(req) & set(prod_dims):
        return 5.0, [f"Abmessungen teilweise passend ({required_dims})"]
    return -10.0, [f"Abmessungen abweichend: gefordert {required_dims}"]


def _description_hash(description: str) -> str:
    """Hash the normalized description for override matching."""
    normalized = re.sub(r"\s+", " ", description.strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()


def _find_overrides(db: Session, position: LVPosition) -> list[ManualOverride]:
    """Find manual overrides matching this position."""
    desc_hash = _description_hash(position.description)
    overrides = list(db.scalars(
        select(ManualOverride)
        .where(ManualOverride.description_hash == desc_hash)
        .order_by(ManualOverride.override_count.desc())
        .limit(3)
    ))
    return overrides


def load_active_products(db: Session) -> list[Product]:
    """Load all active products once. Pass the result to suggest_products_for_position."""
    return list(db.scalars(select(Product).where(Product.status == "aktiv")))


def _is_reference_product(product: Product) -> bool:
    artikel_id = product.artikel_id or ""
    return artikel_id.startswith("REF-")


def suggest_products_for_position(
    db: Session,
    position: LVPosition,
    limit: int = 3,
    products: list[Product] | None = None,
) -> list[ProductSuggestion]:
    # LLM classification is authoritative — skip service positions entirely
    if position.position_type == "dienstleistung":
        return []

    # LLM relevance filter: skip positions classified as not catalog-relevant
    # (e.g. Stützmauern, Bordsteine, Pflaster — not sold by Baustoffhandel)
    # Use `is False` so that None (unknown) still goes through normal matching
    if position.parameters.sortiment_relevant is False:
        return []

    category, subcategory = _guess_category(position)

    # Reject positions where LLM is unsure AND no technical parameters exist
    if (
        position.parameters.sortiment_relevant is None
        and category is None
        and position.parameters.nominal_diameter_dn is None
        and position.parameters.material is None
        and position.parameters.load_class is None
    ):
        return []
    quantity = float(position.quantity or 1)
    quantity_defaulted = position.quantity is None or position.quantity == 0
    lower_text = f"{position.description} {position.raw_text}".lower()
    # Fallback heuristic for regex-parsed positions (position_type is None)
    is_service_position = position.position_type is None and any(hint in lower_text for hint in SERVICE_HINTS)

    is_relevant_position = (
        category is not None
        or position.parameters.nominal_diameter_dn is not None
        or position.parameters.secondary_nominal_diameter_dn is not None
        or position.parameters.load_class is not None
        or position.parameters.material is not None
        or position.parameters.system_family is not None
    )
    if not is_relevant_position or (is_service_position and category is None):
        return []

    if products is None:
        products = load_active_products(db)

    position_tokens = _extract_tokens(f"{position.description} {position.raw_text}")
    position_product_type = _detect_product_type(
        f"{position.description} {position.raw_text}",
        category,
        subcategory,
    )

    # Reject clear non-catalog positions, but allow explicit technical product families
    # such as Kabelschächte or Laternenhülsen even if the text mentions "Fundament" etc.
    non_product_hit = any(hint in lower_text for hint in NON_PRODUCT_HINTS)
    if non_product_hit and position_product_type not in {"kabelschacht", "laternenhuelse"}:
        return []

    if _is_modifier_position(position, position_product_type):
        return []

    if position.parameters.components and len(position.parameters.components) > 1:
        if position_product_type in {"revisionsschacht", "einlaufkasten", "ablauf", "rinne"}:
            return []

    scored: list[tuple[float, Product, list[str], list[ScoreBreakdown]]] = []
    cat_norm = _normalize(category) if category else ""
    for product in products:
        if category:
            product_category = _normalize(product.kategorie)
            is_cat_match = cat_norm in product_category or product_category in cat_norm
            is_related = product_category in _RELATED_CATEGORIES.get(cat_norm, set())
            allow_form_piece = False
            if cat_norm in {"formstuecke", "formstücke"}:
                product_text = f"{product.artikelname} {product.artikelbeschreibung or ''} {product.unterkategorie or ''}"
                product_type = _detect_product_type(product_text, product.kategorie, product.unterkategorie)
                allow_form_piece = product_type is not None
            if not is_cat_match and not is_related:
                if not allow_form_piece and (not subcategory or _normalize(subcategory) not in _normalize(product.unterkategorie or "")):
                    continue

        if _has_hard_conflict(position, category, subcategory, position_product_type, product):
            continue

        reasons: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        score = 0.0

        category_score, category_reasons = _category_match_score(category, subcategory, product)
        dn_sc, dn_reasons = _dn_score(position.parameters.nominal_diameter_dn, product)
        secondary_dn_sc, secondary_dn_reasons = _secondary_dn_score(position.parameters.secondary_nominal_diameter_dn, product)
        load_sc, load_reasons = _load_class_score(position.parameters.load_class, product)
        material_sc, material_reasons = _material_score(position.parameters.material, product)
        norm_sc, norm_reasons = _norm_score(position.parameters.norm, product)
        sn_sc, sn_reasons = _sn_score(position.parameters.stiffness_class_sn, product)
        text_sc = _text_similarity_score(position_tokens, product)
        ptype_sc, ptype_reasons = _product_type_score(position_product_type, product)
        dims_sc, dims_reasons = _dimensions_score(position.parameters.dimensions, product)
        length_sc, length_reasons = _pipe_length_score(position.parameters.pipe_length_mm, product)
        angle_sc, angle_reasons = _angle_score(position.parameters.angle_deg, product)
        app_sc, app_reasons = _application_area_score(position.parameters.application_area, product)
        height_sc, height_reasons = _height_score(position, position_product_type, product)
        system_sc, system_reasons = _system_family_score(position.parameters.system_family, product)
        connection_sc, connection_reasons = _connection_type_score(position.parameters.connection_type, product)
        seal_sc, seal_reasons = _seal_type_score(position.parameters.seal_type, product)
        compatible_systems_sc, compatible_systems_reasons = _compatible_systems_score(position.parameters.compatible_systems, product)

        score += category_score + dn_sc + secondary_dn_sc + load_sc + material_sc + norm_sc + sn_sc + text_sc + ptype_sc + dims_sc + length_sc + angle_sc + app_sc + height_sc + system_sc + connection_sc + seal_sc + compatible_systems_sc

        reasons.extend(category_reasons)
        reasons.extend(dn_reasons)
        reasons.extend(secondary_dn_reasons)
        reasons.extend(load_reasons)
        reasons.extend(material_reasons)
        reasons.extend(norm_reasons)
        reasons.extend(sn_reasons)
        reasons.extend(ptype_reasons)
        reasons.extend(dims_reasons)
        reasons.extend(length_reasons)
        reasons.extend(angle_reasons)
        reasons.extend(app_reasons)
        reasons.extend(height_reasons)
        reasons.extend(system_reasons)
        reasons.extend(connection_reasons)
        reasons.extend(seal_reasons)
        reasons.extend(compatible_systems_reasons)

        breakdown.append(ScoreBreakdown(component="Kategorie", points=round(category_score, 1), detail="; ".join(category_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Produkttyp", points=round(ptype_sc, 1), detail="; ".join(ptype_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="DN", points=round(dn_sc, 1), detail="; ".join(dn_reasons) or "-"))
        if secondary_dn_sc != 0:
            breakdown.append(ScoreBreakdown(component="Anschluss-DN", points=round(secondary_dn_sc, 1), detail="; ".join(secondary_dn_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Belastungsklasse", points=round(load_sc, 1), detail="; ".join(load_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Werkstoff", points=round(material_sc, 1), detail="; ".join(material_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Norm", points=round(norm_sc, 1), detail="; ".join(norm_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="SN-Klasse", points=round(sn_sc, 1), detail="; ".join(sn_reasons) or "-"))
        if dims_sc != 0:
            breakdown.append(ScoreBreakdown(component="Abmessungen", points=round(dims_sc, 1), detail="; ".join(dims_reasons) or "-"))
        if length_sc != 0:
            breakdown.append(ScoreBreakdown(component="Baulänge", points=round(length_sc, 1), detail="; ".join(length_reasons) or "-"))
        if angle_sc != 0:
            breakdown.append(ScoreBreakdown(component="Winkel", points=round(angle_sc, 1), detail="; ".join(angle_reasons) or "-"))
        if app_sc != 0:
            breakdown.append(ScoreBreakdown(component="Einsatzbereich", points=round(app_sc, 1), detail="; ".join(app_reasons) or "-"))
        if height_sc != 0:
            breakdown.append(ScoreBreakdown(component="Höhe", points=round(height_sc, 1), detail="; ".join(height_reasons) or "-"))
        if system_sc != 0:
            breakdown.append(ScoreBreakdown(component="Systemfamilie", points=round(system_sc, 1), detail="; ".join(system_reasons) or "-"))
        if connection_sc != 0:
            breakdown.append(ScoreBreakdown(component="Anschlussart", points=round(connection_sc, 1), detail="; ".join(connection_reasons) or "-"))
        if seal_sc != 0:
            breakdown.append(ScoreBreakdown(component="Dichtung", points=round(seal_sc, 1), detail="; ".join(seal_reasons) or "-"))
        if compatible_systems_sc != 0:
            breakdown.append(ScoreBreakdown(component="Systemkompatibilität", points=round(compatible_systems_sc, 1), detail="; ".join(compatible_systems_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Textähnlichkeit", points=round(text_sc, 1), detail="-"))

        stock = product.lager_gesamt or 0
        if stock >= math.ceil(quantity):
            score += 4
            reasons.append("Sofort aus Lager verfügbar")
            breakdown.append(ScoreBreakdown(component="Lager", points=4.0, detail="Sofort verfügbar"))
        elif stock > 0:
            score += 1
            reasons.append("Teilmenge auf Lager")
            breakdown.append(ScoreBreakdown(component="Lager", points=1.0, detail="Teilmenge"))
        else:
            score -= 3
            reasons.append("Aktuell kein Lagerbestand")
            breakdown.append(ScoreBreakdown(component="Lager", points=-3.0, detail="Kein Bestand"))

        delivery_sc = 0.0
        if product.lieferant_1_lieferzeit_tage is not None:
            if product.lieferant_1_lieferzeit_tage <= 3:
                delivery_sc = 2.0
            elif product.lieferant_1_lieferzeit_tage >= 10:
                delivery_sc = -1.0
        score += delivery_sc
        breakdown.append(ScoreBreakdown(component="Lieferzeit", points=delivery_sc, detail=f"{product.lieferant_1_lieferzeit_tage or '?'} Tage"))

        if _is_reference_product(product):
            score -= 2.0
            reasons.append("Referenzartikel aus Demo-Katalog")
            breakdown.append(ScoreBreakdown(component="Referenzkatalog", points=-2.0, detail="Demo-Referenz statt Echtstammdaten"))

        scored.append((score, product, reasons, breakdown))

    if not scored:
        return []

    grouped_by_id: dict[str, tuple[float, Product, list[str], list[ScoreBreakdown]]] = {}
    for entry in scored:
        s, product, _, _ = entry
        key = product.artikel_id or ""
        existing = grouped_by_id.get(key)
        if existing is None or s > existing[0]:
            grouped_by_id[key] = entry

    # Require category match + at least one technical parameter match to pass
    min_score = _minimum_score(position, category, position_product_type)
    ranked = sorted(grouped_by_id.values(), key=lambda item: item[0], reverse=True)

    # Collapse product-family duplicates: identical (artikelname, hersteller,
    # DN, SN) in different stock lengths count as one suggestion. Keep the
    # highest-scored variant and append a hint about the other lengths so the
    # Mitarbeiter still knows the range exists. Without this, the carousel
    # shows 3× the same pipe in 1m/3m/6m and crowds out real alternatives.
    family_seen: dict[tuple, int] = {}
    deduped: list = []
    for entry in ranked:
        if entry[0] < min_score:
            continue
        _, product, reasons, breakdown = entry
        family_key = (
            (product.artikelname or "").strip().lower(),
            (product.hersteller or "").strip().lower(),
            product.nennweite_dn,
            (product.steifigkeitsklasse_sn or "").strip().lower(),
        )
        if family_key in family_seen:
            idx = family_seen[family_key]
            prev_score, prev_product, prev_reasons, prev_breakdown = deduped[idx]
            length_m = product.laenge_mm / 1000 if product.laenge_mm else None
            prev_length_m = prev_product.laenge_mm / 1000 if prev_product.laenge_mm else None
            lengths = set()
            for val in (length_m, prev_length_m):
                if val is not None:
                    lengths.add(f"{val:g} m")
            hint = f"Auch in Längen: {', '.join(sorted(lengths))}" if lengths else "Mehrere Stangenlängen verfügbar"
            existing_idx = next(
                (i for i, r in enumerate(prev_reasons) if r.startswith("Auch in Längen") or r.startswith("Mehrere Stangenlängen")),
                None,
            )
            if existing_idx is None:
                # Prepend so it survives the most_common(N) reason cap below.
                prev_reasons.insert(0, hint)
            elif length_m is not None:
                existing_lengths = {s.strip() for s in prev_reasons[existing_idx].replace("Auch in Längen:", "").split(",") if s.strip()}
                existing_lengths.add(f"{length_m:g} m")
                prev_reasons[existing_idx] = f"Auch in Längen: {', '.join(sorted(existing_lengths))}"
            continue
        family_seen[family_key] = len(deduped)
        deduped.append(entry)

    final_candidates = deduped[:limit]

    # Feature 6: Inject manual override suggestions
    override_suggestions: list[ProductSuggestion] = []
    overrides = _find_overrides(db, position)
    existing_ids = {entry[1].artikel_id for entry in final_candidates} if final_candidates else set()
    for ov in overrides:
        if ov.chosen_artikel_id in existing_ids:
            continue
        ov_product = db.scalar(select(Product).where(Product.artikel_id == ov.chosen_artikel_id))
        if not ov_product or ov_product.status != "aktiv":
            continue
        unit_price = _price_for_quantity(ov_product, quantity)
        total_price = round((unit_price or 0.0) * quantity, 2) if unit_price is not None else None
        sn_val = None
        if ov_product.steifigkeitsklasse_sn and re.search(r"(\d+)", ov_product.steifigkeitsklasse_sn):
            sn_val = int(re.search(r"(\d+)", ov_product.steifigkeitsklasse_sn).group(1))
        override_suggestions.append(ProductSuggestion(
            artikel_id=ov_product.artikel_id,
            artikelname=ov_product.artikelname,
            hersteller=ov_product.hersteller,
            category=ov_product.kategorie,
            subcategory=ov_product.unterkategorie,
            dn=ov_product.nennweite_dn,
            sn=sn_val,
            load_class=ov_product.belastungsklasse,
            norm=ov_product.norm_primaer,
            stock=ov_product.lager_gesamt,
            delivery_days=ov_product.lieferant_1_lieferzeit_tage,
            price_net=unit_price,
            total_net=total_price,
            currency=ov_product.waehrung or "EUR",
            score=0,
            reasons=[f"Häufig gewählt ({ov.override_count}x)"],
            warnings=[],
            score_breakdown=[],
            is_override=True,
        ))
        existing_ids.add(ov_product.artikel_id)

    if not final_candidates:
        return override_suggestions

    suggestions: list[ProductSuggestion] = []
    for s, product, reasons, breakdown in final_candidates:
        unit_price = _price_for_quantity(product, quantity)
        total_price = round((unit_price or 0.0) * quantity, 2) if unit_price is not None else None

        reasons_counter = Counter(reasons)
        deduped_reasons = [reason for reason, _count in reasons_counter.most_common(7)]

        suggestion_warnings: list[str] = []
        if quantity_defaulted:
            suggestion_warnings.append("Menge nicht erkannt, Standard 1 verwendet")
        if unit_price is not None and unit_price == 0.0:
            suggestion_warnings.append("Listenpreis ist 0 EUR")
        if unit_price is None:
            suggestion_warnings.append("Kein Preis verfügbar")

        suggestions.append(
            ProductSuggestion(
                artikel_id=product.artikel_id,
                artikelname=product.artikelname,
                hersteller=product.hersteller,
                category=product.kategorie,
                subcategory=product.unterkategorie,
                dn=product.nennweite_dn,
                sn=int(re.search(r"(\d+)", product.steifigkeitsklasse_sn).group(1)) if product.steifigkeitsklasse_sn and re.search(r"(\d+)", product.steifigkeitsklasse_sn) else None,
                load_class=product.belastungsklasse,
                norm=product.norm_primaer,
                stock=product.lager_gesamt,
                delivery_days=product.lieferant_1_lieferzeit_tage,
                price_net=unit_price,
                total_net=total_price,
                currency=product.waehrung or "EUR",
                score=round(s, 2),
                reasons=deduped_reasons,
                warnings=suggestion_warnings,
                score_breakdown=breakdown,
            )
        )

    # Append override suggestions after regular ones
    suggestions.extend(override_suggestions)
    return suggestions


def suggest_products_for_component(
    db: Session,
    component: ComponentRequirement,
    products: list[Product],
    limit: int = 3,
    parent_position: LVPosition | None = None,
) -> list[ProductSuggestion]:
    """Match a single component of a multi-part position by building a synthetic LVPosition.

    Inherits missing parameters (load_class, material) from parent_position if available.
    """
    component_text = component.description or component.component_name

    # Inherit missing parameters from parent position
    load_class = component.load_class
    material = component.material
    non_inherited_material_types = {"Schachtfutter", "Schmutzfangeimer", "Rost", "Stirnwand", "Abdeckung", "Einlaufkasten", "Aufsatz"}
    if parent_position:
        if not load_class and parent_position.parameters.load_class:
            load_class = parent_position.parameters.load_class
        if (
            not material
            and parent_position.parameters.material
            and (component.product_subcategory or component.component_name) not in non_inherited_material_types
        ):
            material = parent_position.parameters.material

    synthetic = LVPosition(
        id=f"_comp_{component.component_name}",
        ordnungszahl="",
        description=component.component_name,
        raw_text=component_text,
        quantity=component.quantity,
        unit="Stk",
        billable=True,
        position_type="material",
        parameters=TechnicalParameters(
            product_category=component.product_category,
            product_subcategory=component.product_subcategory,
            nominal_diameter_dn=component.nominal_diameter_dn,
            secondary_nominal_diameter_dn=component.secondary_nominal_diameter_dn,
            material=material,
            system_family=component.system_family,
            load_class=load_class,
            dimensions=component.dimensions,
            connection_type=component.connection_type,
            installation_area=component.installation_area,
        ),
    )
    return suggest_products_for_position(db, synthetic, limit=limit, products=products)
