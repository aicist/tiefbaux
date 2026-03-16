from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ManualOverride, Product
from ..schemas import LVPosition, ProductSuggestion, ScoreBreakdown

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
    "reduzierstück": ["reduzierstück", "reduktion", "übergang"],
    "schachtboden": ["schachtboden", "schachtunterteil"],
    "schachtrohr": ["schachtrohr"],
    "konus": ["konus", "schachthals", "schachtkonus"],
    "abdeckung": ["abdeckung", "deckel", "abdeckplatte", "wannenschachtabdeckung"],
    "ablauf": ["ablauf", "straßenablauf", "hofablauf", "einlauf"],
    "rinne": ["rinne", "entwässerungsrinne", "schwerlastrinne", "powerdrain", "multiline"],
    "auslauf": ["auslauf", "auslaufstück", "froschklappe"],
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
)


_UMLAUT_MAP = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "ae", "Ö": "oe", "Ü": "ue",
})


def _normalize(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower().translate(_UMLAUT_MAP)


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


def _detect_product_type(text: str) -> str | None:
    """Detect what type of product is described (rohr, bogen, abzweig, etc.).

    Uses a priority system: specific types (bogen, abzweig, muffe, konus, ...)
    are checked first.  Generic "rohr" is only returned when no more specific
    type matches.  This prevents "Formteil (Bögen) zu KG-Rohr DN200" from
    being classified as "rohr".
    """
    lower = text.lower()

    # High-priority: check specific product types first
    priority_types = [
        "bogen", "abzweig", "muffe", "reduzierstück", "konus",
        "schachtboden", "schachtrohr", "abdeckung", "ablauf", "auslauf",
    ]
    for ptype in priority_types:
        for kw in PRODUCT_TYPE_KEYWORDS[ptype]:
            if kw in lower:
                return ptype

    # Low-priority: generic "rohr"
    for kw in PRODUCT_TYPE_KEYWORDS["rohr"]:
        if kw in lower:
            return "rohr"

    return None


def _product_type_score(position_type: str | None, product: Product) -> tuple[float, list[str]]:
    """Score how well the product type matches what the LV position describes."""
    if not position_type:
        return 0.0, []

    product_text = f"{product.artikelname} {product.artikelbeschreibung or ''} {product.unterkategorie or ''}"
    product_type = _detect_product_type(product_text)

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
    }
    pair = (position_type, product_type)
    reverse_pair = (product_type, position_type)
    if pair in related:
        return related[pair], [f"Produkttyp ähnlich ({product_type})"]
    if reverse_pair in related:
        return related[reverse_pair], [f"Produkttyp ähnlich ({product_type})"]

    # Clear mismatch: LV says "Rohr" but product is "Abzweig" etc.
    return -20.0, [f"Produkttyp falsch ({position_type} ≠ {product_type})"]


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
    return (len(overlap) / max(1, len(position_tokens))) * 20


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
        score += 35
        reasons.append(f"Kategorie passt ({product.kategorie})")
    elif category_norm and (category_norm in product_category or product_category in category_norm):
        score += 20
        reasons.append("Kategorie ähnlich")
    elif category_norm and product_category in _RELATED_CATEGORIES.get(category_norm, set()):
        score += 20
        reasons.append(f"Kategorie verwandt ({product.kategorie})")

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


def _load_class_score(required: str | None, product: Product) -> tuple[float, list[str]]:
    if not required:
        return 0.0, []

    required_rank = LOAD_RANK.get(required.upper())
    product_class = (product.belastungsklasse or "").upper()
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

    if required and (required in product_material or product_material in required):
        return 10.0, [f"Werkstoff passt ({product.werkstoff})"]

    # Explicit material mismatch: position says HDPE but product is PP etc.
    return -12.0, [f"Werkstoff abweichend ({product.werkstoff} ≠ {required_material})"]


def _norm_score(required_norm: str | None, product: Product) -> tuple[float, list[str]]:
    if not required_norm:
        return 0.0, []

    required = _normalize(required_norm)
    product_norm = _normalize(product.norm_primaer)

    if not product_norm:
        return 0.0, []

    if required and required in product_norm:
        return 12.0, [f"Norm passt ({product.norm_primaer})"]

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

    # Product SN too low — hard penalty, safety-critical
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
    quantity = float(position.quantity or 1)
    quantity_defaulted = position.quantity is None or position.quantity == 0
    lower_text = f"{position.description} {position.raw_text}".lower()
    # Fallback heuristic for regex-parsed positions (position_type is None)
    is_service_position = position.position_type is None and any(hint in lower_text for hint in SERVICE_HINTS)

    # Reject positions whose description clearly indicates non-catalog items
    # (catches LLM mis-classifications like "Asphalt" → "Straßenentwässerung")
    if any(hint in lower_text for hint in NON_PRODUCT_HINTS):
        return []

    is_relevant_position = (
        category is not None
        or position.parameters.nominal_diameter_dn is not None
        or position.parameters.load_class is not None
        or position.parameters.material is not None
    )
    if not is_relevant_position or (is_service_position and category is None):
        return []

    if products is None:
        products = load_active_products(db)

    position_tokens = _extract_tokens(f"{position.description} {position.raw_text}")
    position_product_type = _detect_product_type(f"{position.description} {position.raw_text}")

    scored: list[tuple[float, Product, list[str], list[ScoreBreakdown]]] = []
    cat_norm = _normalize(category) if category else ""
    for product in products:
        if category:
            product_category = _normalize(product.kategorie)
            is_cat_match = cat_norm in product_category or product_category in cat_norm
            is_related = product_category in _RELATED_CATEGORIES.get(cat_norm, set())
            if not is_cat_match and not is_related:
                if not subcategory or _normalize(subcategory) not in _normalize(product.unterkategorie or ""):
                    continue

        reasons: list[str] = []
        breakdown: list[ScoreBreakdown] = []
        score = 0.0

        category_score, category_reasons = _category_match_score(category, subcategory, product)
        dn_sc, dn_reasons = _dn_score(position.parameters.nominal_diameter_dn, product)
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

        score += category_score + dn_sc + load_sc + material_sc + norm_sc + sn_sc + text_sc + ptype_sc + dims_sc + length_sc + angle_sc + app_sc

        reasons.extend(category_reasons)
        reasons.extend(dn_reasons)
        reasons.extend(load_reasons)
        reasons.extend(material_reasons)
        reasons.extend(norm_reasons)
        reasons.extend(sn_reasons)
        reasons.extend(ptype_reasons)
        reasons.extend(dims_reasons)
        reasons.extend(length_reasons)
        reasons.extend(angle_reasons)
        reasons.extend(app_reasons)

        breakdown.append(ScoreBreakdown(component="Kategorie", points=round(category_score, 1), detail="; ".join(category_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="Produkttyp", points=round(ptype_sc, 1), detail="; ".join(ptype_reasons) or "-"))
        breakdown.append(ScoreBreakdown(component="DN", points=round(dn_sc, 1), detail="; ".join(dn_reasons) or "-"))
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

        scored.append((score, product, reasons, breakdown))

    if not scored:
        return []

    ranked = sorted(scored, key=lambda item: item[0], reverse=True)[: max(limit * 2, 6)]

    grouped_by_id: dict[str, tuple[float, Product, list[str], list[ScoreBreakdown]]] = {}
    for entry in ranked:
        s, product, _, _ = entry
        key = product.artikel_id or ""
        existing = grouped_by_id.get(key)
        if existing is None or s > existing[0]:
            grouped_by_id[key] = entry

    # Require category match + at least one technical parameter match to pass
    min_score = 38.0 if category else 45.0
    final_candidates = [
        entry for entry in sorted(grouped_by_id.values(), key=lambda item: item[0], reverse=True) if entry[0] >= min_score
    ][:limit]

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
        deduped_reasons = [reason for reason, _count in reasons_counter.most_common(5)]

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
