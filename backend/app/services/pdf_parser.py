from __future__ import annotations

import io
import re
from collections.abc import Iterable

import pdfplumber
from pypdf import PdfReader

from ..schemas import LVPosition


# Match only ordinal numbers that are followed by whitespace/end, not by decimal/thousand fragments.
POSITION_RE = re.compile(r"^(?P<ord>\d+(?:\.\d+){1,5})(?=\s|$)\s*\.?\s*(?P<desc>.*)$")
QUANTITY_RE = re.compile(
    r"(?P<qty>\d{1,3}(?:[\.\s]\d{3})*(?:,\d+)?)\s*(?P<unit>m²|m2|m3|m³|m|Stck\.?|Stk\.?|St\.?|Stück|StD|Std|kg|to|t|h|lfdm|lfm|Psch|psch|Pausch|mWo|Wo)\b",
    re.IGNORECASE,
)
STRICT_QUANTITY_LINE_RE = re.compile(
    r"^\s*(?P<qty>\d{1,3}(?:[\.\s]\d{3})*(?:,\d+)?)\s*(?P<unit>m²|m2|m3|m³|m|Stck\.?|Stk\.?|St\.?|Stück|StD|Std|kg|to|t|h|lfdm|lfm|Psch|psch|Pausch|mWo|Wo)\b",
    re.IGNORECASE,
)


def _normalize_line(raw_line: str) -> str:
    line = raw_line.replace("\t", " ").replace("\xa0", " ")
    # Normalize "1 . 5 . 11" -> "1.5.11"
    line = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", line)
    # Normalize noisy GAEB-like separators: "1.2...8" -> "1.2.8"
    line = re.sub(r"\.{2,}", ".", line)
    # Normalize KEMNA style "5.3.2 . 8 . Text" -> "5.3.2.8 Text"
    line = re.sub(r"^(\d+(?:\.\d+)+)\s*\.\s*(\d+)\s*\.\s*", r"\1.\2 ", line)
    line = re.sub(r"\s+", " ", line).strip()
    return line


def _is_header_or_noise(line: str) -> bool:
    if not line:
        return True
    blocked_prefixes = (
        "Ordnungszahl Leistungsbeschreibung",
        "in EUR",
        "Inhaltsverzeichnis",
        "Ausschreibungs-LV",
        "Langtext:",
        "Leistungsverzeichnis",
        "Projekt:",
        "Immobilien Bremen AöR",
        "Gewerk:",
        "Menge Einheit E-Preis",
        "Übertrag:",
    )
    if line.startswith(blocked_prefixes):
        return True
    # Skip table-of-contents rows with long dot leaders
    if line.count(".") >= 10 and re.search(r"\d+\s*$", line):
        return True
    return False


def _to_float_german(value: str) -> float | None:
    cleaned = value.replace(" ", "")
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_quantity(text: str) -> tuple[float | None, str | None]:
    # Prefer lines that start with quantity + unit (typical LV amount rows).
    for line in reversed(text.splitlines()):
        strict_match = STRICT_QUANTITY_LINE_RE.match(line.strip())
        if strict_match:
            quantity = _to_float_german(strict_match.group("qty"))
            unit = strict_match.group("unit").replace(".", "")
            return quantity, unit

    best_match = None
    for match in QUANTITY_RE.finditer(text):
        before = text[max(0, match.start() - 2) : match.start()]
        after = text[match.end() : min(len(text), match.end() + 2)]
        context_before = text[max(0, match.start() - 10) : match.start()].lower()
        context_after = text[match.end() : min(len(text), match.end() + 8)].lower()
        # Avoid dimension patterns such as "4 x 3 m" or "3,5 m breit".
        if "x" in before.lower() or "/" in before:
            continue
        if after.strip().startswith(("bis", "breit", "hoch", "lang")):
            continue
        if "ca." in context_before or "max." in context_before:
            continue
        if "ü." in context_after or "nn" in context_after:
            continue
        best_match = match

    if best_match is None:
        return None, None

    quantity = _to_float_german(best_match.group("qty"))
    unit = best_match.group("unit")
    if unit:
        unit = unit.replace(".", "")
    return quantity, unit


def _extract_pdf_lines(pdf_bytes: bytes) -> list[str]:
    lines: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                for raw_line in page_text.splitlines():
                    line = _normalize_line(raw_line)
                    if _is_header_or_noise(line):
                        continue
                    lines.append(line)
    except Exception:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            page_text = page.extract_text() or ""
            for raw_line in page_text.splitlines():
                line = _normalize_line(raw_line)
                if _is_header_or_noise(line):
                    continue
                lines.append(line)
    return lines


def _collect_position_blocks(lines: Iterable[str]) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    current_ord: str | None = None
    current_lines: list[str] = []

    for line in lines:
        match = POSITION_RE.match(line)
        if match:
            ordnungszahl = match.group("ord")
            depth = ordnungszahl.count(".") + 1
            if depth >= 2:
                if current_ord is not None:
                    blocks.append({"ordnungszahl": current_ord, "lines": current_lines})
                current_ord = ordnungszahl
                desc = match.group("desc").strip()
                current_lines = [desc] if desc else []
                continue

        if current_ord is not None:
            current_lines.append(line)

    if current_ord is not None:
        blocks.append({"ordnungszahl": current_ord, "lines": current_lines})

    return blocks


def _position_completeness_score(position: LVPosition) -> tuple[int, int, int]:
    """Rank duplicate OZ matches by how much usable signal they contain."""
    return (
        1 if position.quantity is not None else 0,
        len(position.raw_text or ""),
        len(position.description or ""),
    )


def _deduplicate_positions(positions: list[LVPosition]) -> list[LVPosition]:
    """Keep one stable position per OZ for regex/pdf fallback parsing.

    Some PDFs extracted via pypdf repeat the same visible content twice.
    OZs should be unique inside an LV, so we keep the most complete entry
    and merge missing scalar fields from duplicate occurrences.
    """
    seen: dict[str, LVPosition] = {}
    ordered: list[str] = []

    for position in positions:
        oz = position.ordnungszahl
        if oz not in seen:
            seen[oz] = position
            ordered.append(oz)
            continue

        existing = seen[oz]
        preferred = existing
        other = position
        if _position_completeness_score(position) > _position_completeness_score(existing):
            preferred = position
            other = existing

        updates: dict[str, object] = {}
        if not preferred.description and other.description:
            updates["description"] = other.description
        if not preferred.raw_text and other.raw_text:
            updates["raw_text"] = other.raw_text
        if preferred.quantity is None and other.quantity is not None:
            updates["quantity"] = other.quantity
        if preferred.unit is None and other.unit is not None:
            updates["unit"] = other.unit
        if not preferred.billable and other.billable:
            updates["billable"] = other.billable

        seen[oz] = preferred.model_copy(update=updates) if updates else preferred

    return [seen[oz] for oz in ordered]


def extract_positions_from_pdf(pdf_bytes: bytes) -> list[LVPosition]:
    lines = _extract_pdf_lines(pdf_bytes)
    blocks = _collect_position_blocks(lines)

    positions: list[LVPosition] = []

    for idx, block in enumerate(blocks, start=1):
        ordnungszahl = str(block["ordnungszahl"])
        text_lines = [line for line in block["lines"] if isinstance(line, str) and line.strip()]
        if not text_lines:
            continue

        # Ignore helper/footer lines after first explicit quantity line.
        for line_index, line in enumerate(text_lines):
            if STRICT_QUANTITY_LINE_RE.match(line.strip()):
                text_lines = text_lines[: line_index + 1]
                break

        raw_text = "\n".join(text_lines)
        description = text_lines[0]
        quantity, unit = _extract_quantity(raw_text)

        non_billable_markers = ("allgemeine beschreibung", "vorbemerkungen")
        marker_hit = any(marker in description.lower() for marker in non_billable_markers)
        # Many LVs use billable OZs like "04.0010" with only one dot segment.
        # Requiring depth >= 3 incorrectly drops complete material sections.
        billable = bool(quantity is not None and not marker_hit)

        positions.append(
            LVPosition(
                id=f"pos-{idx}",
                ordnungszahl=ordnungszahl,
                description=description,
                raw_text=raw_text,
                quantity=quantity,
                unit=unit,
                billable=billable,
            )
        )

    positions = _deduplicate_positions(positions)

    # Keep only billable positions, but if parser fails keep up to first 40 positions as fallback.
    billable_positions = [position for position in positions if position.billable]
    if billable_positions:
        return billable_positions

    return positions[:40]
