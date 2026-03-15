from __future__ import annotations

from collections import defaultdict

from ..schemas import CompatibilityIssue, LVPosition, ProductSuggestion

LOAD_RANK = {
    "A15": 1,
    "B125": 2,
    "C250": 3,
    "D400": 4,
    "E600": 5,
    "F900": 6,
}



def _required_load_class(position: LVPosition) -> str | None:
    if position.parameters.load_class:
        return position.parameters.load_class.upper()

    area = (position.parameters.installation_area or "").lower()
    raw = f"{position.description} {position.raw_text}".lower()

    if "fahrbahn" in area or "fahrbahn" in raw:
        return "D400"
    if "gehweg" in area or "gehweg" in raw:
        return "B125"
    return None



def _is_subcategory(suggestion: ProductSuggestion, needle: str) -> bool:
    combined = f"{suggestion.category or ''} {suggestion.subcategory or ''} {suggestion.artikelname}".lower()
    return needle.lower() in combined



def check_compatibility(selected: list[tuple[LVPosition, ProductSuggestion]]) -> list[CompatibilityIssue]:
    issues: list[CompatibilityIssue] = []

    # Rule: load class must satisfy required class for the position/install area.
    for position, suggestion in selected:
        required = _required_load_class(position)
        if not required:
            continue
        actual = (suggestion.load_class or "").upper()
        if not actual:
            continue

        required_rank = LOAD_RANK.get(required)
        actual_rank = LOAD_RANK.get(actual)
        if required_rank and actual_rank and actual_rank < required_rank:
            issues.append(
                CompatibilityIssue(
                    severity="KRITISCH",
                    rule="Belastungsklasse",
                    message=(
                        f"Position {position.ordnungszahl}: {suggestion.artikel_id} hat Klasse {actual}, "
                        f"erforderlich ist mindestens {required}."
                    ),
                    positions=[position.id],
                )
            )

    # Rule: Schacht chain DN must match.
    schacht_under = [(p, s) for p, s in selected if _is_subcategory(s, "schachtunterteil")]
    schacht_ring = [(p, s) for p, s in selected if _is_subcategory(s, "schachtring")]
    schacht_konus = [(p, s) for p, s in selected if _is_subcategory(s, "konus") or _is_subcategory(s, "schachthals")]

    if schacht_under and schacht_ring:
        ring_dns = {s_ring.dn for _, s_ring in schacht_ring if s_ring.dn}
        for p_under, s_under in schacht_under:
            if s_under.dn and s_under.dn not in ring_dns:
                issues.append(
                    CompatibilityIssue(
                        severity="KRITISCH",
                        rule="Schachtunterteil-Schachtring DN gleich",
                        message=(
                            f"Schachtunterteil {s_under.artikel_id} (DN{s_under.dn}) — "
                            f"kein passender Schachtring mit DN{s_under.dn} im Projekt."
                        ),
                        positions=[p_under.id],
                    )
                )

    if schacht_ring and schacht_konus:
        konus_dns = {s_konus.dn for _, s_konus in schacht_konus if s_konus.dn}
        for p_ring, s_ring in schacht_ring:
            if s_ring.dn and s_ring.dn not in konus_dns:
                issues.append(
                    CompatibilityIssue(
                        severity="KRITISCH",
                        rule="Schachtring-Konus DN gleich",
                        message=(
                            f"Schachtring {s_ring.artikel_id} (DN{s_ring.dn}) — "
                            f"kein passender Konus mit DN{s_ring.dn} im Projekt."
                        ),
                        positions=[p_ring.id],
                    )
                )

    # Rule: Straßenablauf DN must have at least one matching pipe DN in the project.
    ablaeufe = [(p, s) for p, s in selected if _is_subcategory(s, "straßenablauf") or _is_subcategory(s, "strassenablauf")]
    rohre = [(p, s) for p, s in selected if _is_subcategory(s, "kanalrohre") or _is_subcategory(s, "kg-rohr")]

    if ablaeufe and rohre:
        rohr_dns = {s_r.dn for _, s_r in rohre if s_r.dn}
        for p_a, s_a in ablaeufe:
            if s_a.dn and s_a.dn not in rohr_dns:
                issues.append(
                    CompatibilityIssue(
                        severity="KRITISCH",
                        rule="Straßenablauf-Abgang zu Rohr",
                        message=(
                            f"Ablauf {s_a.artikel_id} DN{s_a.dn} — kein passendes Rohr mit DN{s_a.dn} im Projekt gefunden."
                        ),
                        positions=[p_a.id],
                    )
                )

    # Rule: Rinnenrost DN should match at least one Rinnenkoerper DN.
    roste = [(p, s) for p, s in selected if _is_subcategory(s, "rinnenrost")]
    rinnen = [(p, s) for p, s in selected if _is_subcategory(s, "entwässerungsrinne") or _is_subcategory(s, "entwaesserungsrinne")]

    if roste and rinnen:
        rinnen_dns = {s_ri.dn for _, s_ri in rinnen if s_ri.dn}
        for p_ro, s_ro in roste:
            if s_ro.dn and s_ro.dn not in rinnen_dns:
                issues.append(
                    CompatibilityIssue(
                        severity="KRITISCH",
                        rule="Rinnenrost passt zu Rinnenkörper",
                        message=(
                            f"Rost {s_ro.artikel_id} DN{s_ro.dn} — keine passende Rinne mit DN{s_ro.dn} im Projekt."
                        ),
                        positions=[p_ro.id],
                    )
                )

    # Rule: mixed load classes among same installation group -> warning.
    by_area: dict[str, list[tuple[LVPosition, ProductSuggestion]]] = defaultdict(list)
    for position, suggestion in selected:
        area = (position.parameters.installation_area or "unspezifiziert").lower()
        by_area[area].append((position, suggestion))

    for area, entries in by_area.items():
        classes = {(entry[1].load_class or "").upper() for entry in entries if entry[1].load_class}
        if len(classes) > 1 and area in {"fahrbahn", "gehweg"}:
            issues.append(
                CompatibilityIssue(
                    severity="WARNUNG",
                    rule="Belastungsklasse konsistent",
                    message=f"Uneinheitliche Belastungsklassen im Bereich '{area}': {', '.join(sorted(classes))}.",
                    positions=[entry[0].id for entry in entries],
                )
            )

    return issues
