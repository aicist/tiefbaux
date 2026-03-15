"""Post-scoring LLM validation: confirms that scored product suggestions
actually match the LV position's intent. Catches false positives that
slip through the scoring engine (e.g. text similarity on "Beton" matching
Stützmauer to Betonauflagering)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import settings
from ..schemas import LVPosition, ProductSuggestion

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    pass


def _build_validation_prompt(
    pairs: list[tuple[LVPosition, list[ProductSuggestion]]],
) -> tuple[str, str]:
    """Build system instruction and user prompt for validation.

    Returns (system_instruction, user_prompt).
    """
    system = (
        "Du bist ein erfahrener Tiefbau-Fachberater. "
        "Pruefe ob die vorgeschlagenen Produkte tatsaechlich zur LV-Position passen. "
        "Beruecksichtige: Produkttyp, Funktion, Dimensionen, Einsatzbereich. "
        "Ein Produkt passt NUR wenn es die gleiche FUNKTION erfuellt wie in der LV-Position beschrieben.\n\n"
        "Beispiele fuer NICHT passend:\n"
        "- 'Betonauflagering' ist KEIN Match fuer 'Stuetzmauer aus Beton' (unterschiedliche Funktion)\n"
        "- 'KG-Rohr DN150' ist KEIN Match fuer 'Bordstein setzen' (voellig andere Produktkategorie)\n"
        "- 'Schachtring DN1000' ist KEIN Match fuer 'Poller aufstellen'\n\n"
        "Gib ein JSON-Array zurueck. Pro Paar ein Objekt:\n"
        "{ \"pair_index\": int, \"valid\": boolean, \"reason\": string }\n"
        "Gib NUR das JSON-Array zurueck, keine Erklaerung."
    )

    lines: list[str] = []
    pair_idx = 0
    for position, candidates in pairs:
        # Only validate the top candidate per position (reduces pairs, improves index stability)
        top_candidate = candidates[0] if candidates else None
        if top_candidate:
            lines.append(
                f"Paar {pair_idx}:\n"
                f"  LV-Position: {position.ordnungszahl} - {position.description}\n"
                f"  Rohtext: {position.raw_text[:300]}\n"
                f"  Vorgeschlagenes Produkt: {top_candidate.artikelname} "
                f"(Kategorie: {top_candidate.category or '?'}, DN: {top_candidate.dn or '?'}, "
                f"Belastungsklasse: {top_candidate.load_class or '?'})\n"
                f"  Score: {top_candidate.score}"
            )
            pair_idx += 1

    prompt = (
        "Pruefe diese Position-Produkt-Paare. "
        "Ist das Produkt ein sinnvoller Match fuer die LV-Position?\n\n"
        + "\n\n".join(lines)
    )
    return system, prompt


def _call_gemini_validate(
    pairs: list[tuple[LVPosition, list[ProductSuggestion]]],
) -> list[dict[str, Any]]:
    """Call Gemini to validate position-candidate pairs."""
    if not settings.gemini_api_key:
        raise ValidationError("GEMINI_API_KEY not configured")

    system_instruction, prompt = _build_validation_prompt(pairs)

    payload = {
        "system_instruction": {"parts": [{"text": system_instruction}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent"
        f"?key={settings.gemini_api_key}"
    )

    with httpx.Client(timeout=60) as client:
        response = client.post(endpoint, json=payload)

    if response.status_code >= 400:
        raise ValidationError(f"Gemini API error: {response.status_code}")

    data = response.json()
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValidationError(f"Unexpected response format") from exc

    from .ai_interpreter import _normalize_json_array

    normalized = _normalize_json_array(content)
    parsed = json.loads(normalized)

    if not isinstance(parsed, list):
        raise ValidationError("Gemini did not return a JSON array")

    return parsed


def validate_matches(
    position_candidates: list[tuple[LVPosition, list[ProductSuggestion]]],
) -> list[tuple[LVPosition, list[ProductSuggestion]]]:
    """Validate scored candidates via Gemini. Returns filtered list.

    Falls back gracefully: if Gemini fails, returns the original candidates unchanged.
    """
    if not settings.gemini_api_key or not position_candidates:
        return position_candidates

    # Only validate pairs that actually have suggestions
    pairs_with_suggestions = [
        (pos, sugs) for pos, sugs in position_candidates if sugs
    ]
    if not pairs_with_suggestions:
        return position_candidates

    try:
        results = _call_gemini_validate(pairs_with_suggestions)
    except Exception as exc:
        logger.warning("Match validation failed, returning unfiltered: %s", exc)
        return position_candidates

    # Build lookup: pair_index -> validation result
    validation_map: dict[int, dict[str, Any]] = {}
    for result in results:
        idx = result.get("pair_index", -1)
        validation_map[idx] = result

    # Filter candidates based on validation (only top candidate was validated)
    validated: list[tuple[LVPosition, list[ProductSuggestion]]] = []
    pair_idx = 0
    for position, candidates in pairs_with_suggestions:
        if not candidates:
            validated.append((position, candidates))
            continue

        validation = validation_map.get(pair_idx)
        pair_idx += 1

        if validation is None or validation.get("valid", True):
            # LLM says valid or no result — keep all candidates
            validated.append((position, candidates))
        else:
            reason = validation.get("reason", "keine Begruendung")
            top = candidates[0]
            if top.score >= 50:
                # High-score match: keep but warn
                logger.info(
                    "LLM rejected but keeping (score %.0f): %s -> %s (%s)",
                    top.score, position.ordnungszahl, top.artikelname, reason,
                )
                top.warnings.append("LLM-Validierung unsicher")
                validated.append((position, candidates))
            else:
                # Low-score match: remove all candidates for this position
                logger.info(
                    "Match rejected by LLM: %s -> %s (%s)",
                    position.ordnungszahl, top.artikelname, reason,
                )
                validated.append((position, []))

    # Re-add positions that had no suggestions (weren't sent to validation)
    validated_ids = {pos.id for pos, _ in validated}
    for position, candidates in position_candidates:
        if position.id not in validated_ids:
            validated.append((position, candidates))

    return validated
