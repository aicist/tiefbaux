"""Gemini-based PDF offer parsing: extracts structured position data from supplier offer PDFs."""

from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .ai_interpreter import InterpretationError
from .llm_parser import _post_gemini

logger = logging.getLogger(__name__)

MAX_PDF_SIZE = 20_000_000  # 20 MB

OFFER_SYSTEM_INSTRUCTION = (
    "Du bist ein Experte fuer die Analyse von Lieferantenangeboten im Tiefbau-Bereich "
    "(Rohre, Schachtbauteile, Rinnen, Formstücke, Entwässerung).\n\n"
    "Analysiere das folgende PDF-Angebot eines Lieferanten und extrahiere ALLE angebotenen Positionen.\n\n"
    "Fuer jede Position extrahiere:\n"
    "- article_name: string (Artikelbezeichnung / Produktname)\n"
    "- article_number: string | null (Artikelnummer des Lieferanten)\n"
    "- unit_price: number | null (Einzelpreis netto in EUR als Dezimalzahl, z.B. 12.50 fuer 12,50 EUR)\n"
    "- total_price: number | null (Gesamtpreis netto in EUR als Dezimalzahl)\n"
    "- quantity: number | null (Menge)\n"
    "- unit: string | null (Einheit: Stk, m, lfm, kg, etc.)\n"
    "- delivery_days: integer | null (Lieferzeit in Tagen. Bei Wochen: Wochen * 7. Bei 'sofort'/'ab Lager': 1)\n"
    "- ordnungszahl: string | null (Falls der Lieferant eine Ordnungszahl/Positionsnummer aus der "
    "urspruenglichen Anfrage referenziert, z.B. '1.5.3' oder 'OZ 01.0020')\n"
    "- position_number: string | null (Positionsnummer des Lieferanten im Angebot, z.B. 'Pos. 1', '10', 'A1')\n"
    "- notes: string | null (Zusaetzliche Hinweise wie Mindestbestellmenge, Rabatte, Gueltigkeitsdauer)\n\n"
    "WICHTIG:\n"
    "- Preise: Deutsche Zahlenformate umrechnen! 1.234,56 EUR = 1234.56 als JSON-number. "
    "Tausenderpunkt entfernen, Komma durch Punkt ersetzen.\n"
    "- Wenn nur ein Gesamtpreis angegeben ist und die Menge bekannt, berechne den Einzelpreis.\n"
    "- Wenn nur ein Einzelpreis angegeben ist und die Menge bekannt, berechne den Gesamtpreis.\n"
    "- Ueberspringe Kopfzeilen, Fussnoten, AGBs, Bankverbindungen, Versandkosten-Zeilen.\n"
    "- Extrahiere NUR tatsaechlich angebotene Artikel/Positionen.\n"
    "- Wenn das Dokument kein Angebot ist (z.B. AGB, Datenblatt, Lieferschein), gib ein leeres Array [] zurueck.\n\n"
    "Gib ein JSON-Array zurueck. Jedes Element ist ein Objekt mit den oben genannten Feldern.\n"
    "Gib NUR das JSON-Array zurueck, keine Erklaerung."
)


@dataclass
class ParsedOfferPosition:
    article_name: str
    article_number: str | None = None
    unit_price: float | None = None
    total_price: float | None = None
    quantity: float | None = None
    unit: str | None = None
    delivery_days: int | None = None
    ordnungszahl: str | None = None
    position_number: str | None = None
    notes: str | None = None


def _parse_german_number(value: Any) -> float | None:
    """Parse a German-formatted number string into a float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    # Strip whitespace and currency symbols
    cleaned = value.strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not cleaned:
        return None
    # German: 1.234,56 → remove dots (thousands), replace comma with dot
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_int_safe(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def _validate_positions(positions: list[ParsedOfferPosition]) -> list[ParsedOfferPosition]:
    """Filter out invalid positions and log warnings."""
    valid = []
    for pos in positions:
        if not pos.article_name or len(pos.article_name.strip()) < 2:
            logger.debug("Skipping position without article name: %s", pos)
            continue
        if pos.unit_price is not None and pos.unit_price < 0:
            logger.warning("Negative unit price for '%s': %s", pos.article_name, pos.unit_price)
            pos.unit_price = None
        if pos.total_price is not None and pos.total_price < 0:
            pos.total_price = None
        valid.append(pos)
    return valid


def parse_offer_with_gemini(
    email_subject: str = "",
    email_body: str = "",
    pdf_attachments: list[bytes] | None = None,
) -> list[ParsedOfferPosition]:
    """Send email text + optional PDF attachments to Gemini and extract structured offer positions.

    All sources (subject, body, PDFs) are sent in a single Gemini request so the model
    can correlate context across them (e.g. body references OZ, PDF has the price table).

    Raises InterpretationError if Gemini call fails.
    Returns empty list if content is not an offer or contains no positions.
    """
    parts: list[dict[str, Any]] = []

    # Add PDF attachments as inline data
    for pdf_bytes in (pdf_attachments or []):
        if len(pdf_bytes) > MAX_PDF_SIZE:
            logger.warning("PDF too large for Gemini offer parsing: %d bytes, skipping", len(pdf_bytes))
            continue
        parts.append({
            "inline_data": {
                "mime_type": "application/pdf",
                "data": base64.b64encode(pdf_bytes).decode(),
            }
        })

    # Add email text as context
    email_text_parts: list[str] = []
    if email_subject.strip():
        email_text_parts.append(f"E-Mail-Betreff: {email_subject.strip()}")
    if email_body.strip():
        email_text_parts.append(f"E-Mail-Text:\n{email_body.strip()}")

    if parts:
        # PDFs + email context
        prompt = "Analysiere dieses Lieferantenangebot und extrahiere alle Positionen als JSON-Array."
        if email_text_parts:
            prompt += "\n\nZusätzlicher Kontext aus der E-Mail:\n" + "\n\n".join(email_text_parts)
        parts.append({"text": prompt})
    elif email_text_parts:
        # No PDFs — parse offer from email body only
        parts.append({
            "text": (
                "Der folgende E-Mail-Text enthält ein Lieferantenangebot. "
                "Extrahiere alle angebotenen Positionen als JSON-Array.\n\n"
                + "\n\n".join(email_text_parts)
            )
        })
    else:
        return []

    payload: dict[str, Any] = {
        "system_instruction": {"parts": [{"text": OFFER_SYSTEM_INSTRUCTION}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    data = _post_gemini(payload, timeout=60)

    # Extract text from Gemini response
    raw_text = ""
    try:
        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            raw_text = "".join(p.get("text", "") for p in parts)
    except (IndexError, KeyError, TypeError):
        raise InterpretationError("Unexpected Gemini response structure for offer PDF")

    if not raw_text.strip():
        return []

    # Parse JSON
    try:
        items = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON array from response
        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if match:
            try:
                items = json.loads(match.group())
            except json.JSONDecodeError:
                logger.warning("Could not parse Gemini offer response as JSON")
                return []
        else:
            return []

    if not isinstance(items, list):
        items = [items] if isinstance(items, dict) else []

    # Convert raw dicts to typed dataclass instances
    positions: list[ParsedOfferPosition] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        pos = ParsedOfferPosition(
            article_name=str(item.get("article_name", "")).strip(),
            article_number=item.get("article_number"),
            unit_price=_parse_german_number(item.get("unit_price")),
            total_price=_parse_german_number(item.get("total_price")),
            quantity=_parse_german_number(item.get("quantity")),
            unit=item.get("unit"),
            delivery_days=_parse_int_safe(item.get("delivery_days")),
            ordnungszahl=item.get("ordnungszahl"),
            position_number=item.get("position_number"),
            notes=item.get("notes"),
        )
        positions.append(pos)

    return _validate_positions(positions)
