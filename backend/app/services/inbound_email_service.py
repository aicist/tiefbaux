from __future__ import annotations

import email
import hashlib
import imaplib
import io
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import InboundEmailEvent, Kunde, LVProject, LVProjectPosition, ProjectFile, Supplier, SupplierInquiry, SupplierOffer
from ..schemas import LVPosition, ProjectMetadata
from .ai_interpreter import _infer_with_heuristics, enrich_positions_with_parameters
from .llm_parser import _inherit_reference_context, _merge_heuristic_parameters, finalize_position_descriptions, parse_lv_with_llm
from .offer_pdf_parser import ParsedOfferPosition, parse_offer_with_gemini
from .pdf_parser import extract_positions_from_pdf

logger = logging.getLogger(__name__)

PENDING_INQUIRY_STATUSES = ("offen", "angefragt")
_INQUIRY_PROGRESS_STATUSES = ("angefragt", "angebot_erhalten")

_INQ_REF_PATTERN = re.compile(r"TBX-INQ[:#\s-]*(\d+)", re.IGNORECASE)
_PROJ_OZ_REF_PATTERN = re.compile(
    r"TBX-PROJ[:#\s-]*(\d+)[^\n\r]{0,120}?OZ[:#\s-]*([0-9]{1,3}(?:\.[0-9]{1,4}){1,3})",
    re.IGNORECASE,
)
_OZ_PATTERN = re.compile(r"\b\d{1,3}(?:\.\d{1,4}){1,3}\b")
_PRICE_PATTERN = re.compile(
    r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{2})|\d+(?:[.,]\d{2}))\s*(?:€|eur)\b",
    re.IGNORECASE,
)
_DELIVERY_PATTERN = re.compile(
    r"lieferzeit[^0-9]{0,12}(\d{1,3})\s*(tage|werktage|wochen)",
    re.IGNORECASE,
)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"[ \t]+")
_ORIGINAL_RECIPIENT_PATTERN = re.compile(
    r"(?:original[-\s]*empf(?:a|ä)nger|original[-\s]*recipient)\s*:\s*([^\s,;<>]+@[^\s,;<>]+)",
    re.IGNORECASE,
)
_GENERIC_EMAIL_PATTERN = re.compile(r"\b([A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,})\b", re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"[a-z0-9]{3,}", re.IGNORECASE)
_NON_LV_PDF_HINTS = (
    "invoice",
    "receipt",
    "statement",
    "billing",
    "stripe",
    "zahlungsbeleg",
    "beleg",
    "rechnung",
    "abrechnung",
    "quittung",
)
_LV_PDF_HINTS = (
    "lv",
    "leistungsverzeichnis",
    "ausschreibung",
    "anfrage",
    "bauprojekt",
    "bauvorhaben",
    "baustoff",
    "position",
)

_sync_lock = threading.Lock()
_sync_state: dict[str, object] = {
    "running": False,
    "last_started_at": None,
    "last_finished_at": None,
    "last_result": None,
}


@dataclass
class _Attachment:
    filename: str
    content_type: str
    payload: bytes

    @property
    def is_pdf(self) -> bool:
        lower_name = self.filename.lower()
        return lower_name.endswith(".pdf") or "pdf" in (self.content_type or "").lower()


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _safe_filename(filename: str) -> str:
    name = filename.strip() or "attachment.bin"
    name = re.sub(r"[^\w.\-]+", "_", name, flags=re.UNICODE)
    return name[:160] or "attachment.bin"


def _strip_html(text: str) -> str:
    if not text:
        return ""
    plain = _TAG_PATTERN.sub(" ", text)
    plain = unescape(plain)
    plain = re.sub(r"\s*\n\s*", "\n", plain)
    return plain.strip()


def _decode_part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except Exception:
        return payload.decode("utf-8", errors="replace")


def _extract_message_content(msg: Message) -> tuple[str, str, str, datetime | None, str | None, list[_Attachment]]:
    subject = _decode_mime_header(msg.get("Subject"))
    sender_raw = _decode_mime_header(msg.get("From"))
    _, sender_email = parseaddr(sender_raw)
    sender_email = (sender_email or "").strip().lower()

    sent_at: datetime | None = None
    if msg.get("Date"):
        try:
            sent_at = parsedate_to_datetime(msg.get("Date"))
        except Exception:
            sent_at = None

    body_plain_parts: list[str] = []
    body_html_parts: list[str] = []
    attachments: list[_Attachment] = []

    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = (part.get("Content-Disposition") or "").lower()
            content_type = (part.get_content_type() or "").lower()
            filename = part.get_filename()
            if filename:
                decoded_name = _decode_mime_header(filename)
                payload = part.get_payload(decode=True) or b""
                attachments.append(
                    _Attachment(
                        filename=_safe_filename(decoded_name),
                        content_type=content_type,
                        payload=payload,
                    )
                )
                continue
            if "attachment" in content_disposition:
                continue
            if content_type == "text/plain":
                body_plain_parts.append(_decode_part_payload(part))
            elif content_type == "text/html":
                body_html_parts.append(_decode_part_payload(part))
    else:
        content_type = (msg.get_content_type() or "").lower()
        if content_type == "text/html":
            body_html_parts.append(_decode_part_payload(msg))
        else:
            body_plain_parts.append(_decode_part_payload(msg))

    body_plain = "\n\n".join(part.strip() for part in body_plain_parts if part.strip()).strip()
    if not body_plain and body_html_parts:
        body_plain = _strip_html("\n\n".join(body_html_parts))

    return subject, sender_email, body_plain, sent_at, msg.get("Message-ID"), attachments


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception:
        return ""
    chunks: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
    return "\n".join(chunks)


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    cleaned = []
    for line in lines:
        if not line:
            continue
        cleaned.append(_WHITESPACE_PATTERN.sub(" ", line))
    return "\n".join(cleaned).strip()


def _tokenize(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_PATTERN.findall(text or "")}


def _extract_candidate_supplier_emails(sender_email: str, corpus: str) -> set[str]:
    emails: set[str] = set()
    if sender_email:
        emails.add(sender_email.strip().lower())

    for match in _ORIGINAL_RECIPIENT_PATTERN.findall(corpus or ""):
        cleaned = match.strip().lower()
        if "@" in cleaned:
            emails.add(cleaned)

    # Keep this as last fallback only when no explicit source was found.
    if len(emails) <= 1:
        for match in _GENERIC_EMAIL_PATTERN.findall(corpus or ""):
            cleaned = match.strip().lower()
            if "@" in cleaned:
                emails.add(cleaned)
    return emails


def _infer_project_id_hints_from_corpus(db: Session, corpus_tokens: set[str]) -> set[int]:
    if not corpus_tokens:
        return set()

    pending_project_ids_raw = db.execute(
        select(SupplierInquiry.project_id)
        .where(SupplierInquiry.status.in_(PENDING_INQUIRY_STATUSES))
        .where(SupplierInquiry.project_id.is_not(None))
    ).scalars().all()
    pending_project_ids = {int(project_id) for project_id in pending_project_ids_raw if project_id is not None}
    if not pending_project_ids:
        return set()

    ranked: list[tuple[int, int]] = []
    projects = db.execute(select(LVProject).where(LVProject.id.in_(pending_project_ids))).scalars().all()
    for project in projects:
        project_text = " ".join(
            part for part in [
                project.bauvorhaben,
                project.project_name,
                project.filename,
                project.objekt_nr,
            ]
            if part
        )
        overlap = len(_tokenize(project_text) & corpus_tokens)
        if overlap > 0:
            ranked.append((project.id, overlap))

    if not ranked:
        return set()

    ranked.sort(key=lambda item: item[1], reverse=True)
    top_project_id, top_overlap = ranked[0]
    second_overlap = ranked[1][1] if len(ranked) > 1 else -1
    if top_overlap < 2:
        return set()
    if second_overlap >= 0 and (top_overlap - second_overlap) < 2:
        return set()
    return {int(top_project_id)}


def _extract_offer_text_for_oz(corpus: str, ordnungszahl: str | None) -> str | None:
    if not corpus.strip():
        return None
    if not ordnungszahl:
        return None
    escaped_oz = re.escape(ordnungszahl)
    pattern = re.compile(
        rf"({escaped_oz}[\s\S]{{20,2200}}?)(?=\n\s*\d{{1,3}}(?:\.\d{{1,4}}){{1,3}}\b|\Z)",
        re.IGNORECASE,
    )
    match = pattern.search(corpus)
    if not match:
        return None
    return _normalize_text(match.group(1))


def _parse_price(text: str) -> float | None:
    match = _PRICE_PATTERN.search(text)
    if not match:
        return None
    normalized = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except Exception:
        return None


def _parse_delivery_hint(text: str) -> str | None:
    match = _DELIVERY_PATTERN.search(text)
    if not match:
        return None
    return f"{match.group(1)} {match.group(2)}"


def _inquiry_effective_key(inq: SupplierInquiry) -> tuple[int | None, str | None, int, str | None]:
    return (inq.project_id, inq.position_id, inq.supplier_id, inq.ordnungszahl)


def _filter_superseded_open_inquiries(inquiries: list[SupplierInquiry]) -> list[SupplierInquiry]:
    progressed_keys = {
        _inquiry_effective_key(inq)
        for inq in inquiries
        if inq.status in _INQUIRY_PROGRESS_STATUSES
    }
    filtered: list[SupplierInquiry] = []
    for inq in inquiries:
        if inq.status == "offen" and _inquiry_effective_key(inq) in progressed_keys:
            continue
        filtered.append(inq)
    return filtered


def _count_pending_project_inquiries(project_id: int, db: Session) -> int:
    inquiries = db.execute(
        select(SupplierInquiry).where(SupplierInquiry.project_id == project_id)
    ).scalars().all()
    effective = _filter_superseded_open_inquiries(inquiries)
    return sum(1 for inq in effective if inq.status in PENDING_INQUIRY_STATUSES)


def _derive_effective_project_status(project: LVProject, has_pending_inquiries: bool) -> str:
    if has_pending_inquiries:
        return "anfrage_offen"
    if project.offer_pdf_path:
        return "gerechnet"
    return "neu" if (project.status or "neu") == "neu" else "offen"


def _refresh_project_status(project_id: int, db: Session) -> None:
    project = db.get(LVProject, project_id)
    if not project:
        return
    has_pending = _count_pending_project_inquiries(project_id, db) > 0
    project.status = _derive_effective_project_status(project, has_pending)


def _upgrade_position_params(positions: list[LVPosition]) -> list[LVPosition]:
    positions = _inherit_reference_context(positions)
    upgraded: list[LVPosition] = []
    for position in positions:
        inferred = _infer_with_heuristics(position)
        upgraded.append(position.model_copy(update={"parameters": _merge_heuristic_parameters(position, inferred)}))
    return finalize_position_descriptions(upgraded)


def _fallback_parse(pdf_bytes: bytes) -> list[LVPosition]:
    positions = extract_positions_from_pdf(pdf_bytes)
    try:
        positions = enrich_positions_with_parameters(positions)
    except Exception as exc:
        logger.warning("LLM enrichment failed for inbound LV, using regex positions: %s", exc)
    classified: list[LVPosition] = []
    for pos in positions:
        if pos.position_type in ("material", "dienstleistung"):
            classified.append(pos)
            continue
        params = pos.parameters
        inferred_type = "dienstleistung" if params.sortiment_relevant is False else "material"
        classified.append(
            pos.model_copy(
                update={
                    "position_type": inferred_type,
                    "billable": inferred_type == "material",
                }
            )
        )
    return _upgrade_position_params(classified)


def _next_project_number(db: Session) -> str:
    now = datetime.utcnow()
    prefix = f"P-{now:%y%m}-"
    max_nr = db.query(func.max(LVProject.projekt_nr)).filter(LVProject.projekt_nr.like(f"{prefix}%")).scalar()
    if max_nr:
        try:
            last_seq = int(max_nr.split("-")[-1])
        except Exception:
            last_seq = 0
    else:
        last_seq = 0
    return f"{prefix}{last_seq + 1:03d}"


def _store_new_project(
    db: Session,
    content_hash: str,
    filename: str | None,
    positions: list[LVPosition],
    metadata: ProjectMetadata | None,
    pdf_path: str | None,
    fallback_project_name: str | None = None,
    sender_email: str | None = None,
    anfrage_art: str = "submission",
) -> LVProject:
    from .archive_resolvers import (
        resolve_or_create_objekt,
        resolve_or_create_kunde,
        find_shareable_project,
    )

    billable = sum(1 for p in positions if p.billable)
    service = sum(1 for p in positions if p.position_type == "dienstleistung")

    bauvorhaben = metadata.bauvorhaben if metadata else None
    objekt_nr = metadata.objekt_nr if metadata else None
    auftraggeber = metadata.auftraggeber if metadata else None
    submission_date = metadata.submission_date if metadata else None
    kunde_name = metadata.kunde_name if metadata else None
    kunde_adresse = metadata.kunde_adresse if metadata else None

    objekt = resolve_or_create_objekt(
        db,
        bauvorhaben=bauvorhaben,
        objekt_nr=objekt_nr,
        auftraggeber=auftraggeber,
        submission_date=submission_date,
    )
    kunde = resolve_or_create_kunde(
        db,
        name=kunde_name or auftraggeber,
        sender_email=sender_email,
        address=kunde_adresse,
    )
    shareable = find_shareable_project(
        db,
        objekt_id=objekt.id,
        content_hash=content_hash,
    )

    project = LVProject(
        content_hash=content_hash,
        objekt_id=objekt.id,
        kunde_id=kunde.id,
        filename=filename,
        project_name=fallback_project_name,
        total_positions=len(positions),
        billable_positions=billable,
        service_positions=service,
        pdf_path=pdf_path,
        projekt_nr=_next_project_number(db),
        anfrage_art=anfrage_art,
    )
    if metadata:
        project.bauvorhaben = metadata.bauvorhaben
        project.objekt_nr = metadata.objekt_nr
        project.submission_date = metadata.submission_date
        project.auftraggeber = metadata.auftraggeber
        project.kunde_name = metadata.kunde_name
        project.kunde_adresse = metadata.kunde_adresse
        if metadata.bauvorhaben and not project.project_name:
            project.project_name = metadata.bauvorhaben

    if shareable is not None:
        project.selections_json = shareable.selections_json
        project.workstate_json = shareable.workstate_json

    db.add(project)
    db.flush()

    for position in positions:
        db.add(
            LVProjectPosition(
                project_id=project.id,
                position_id=position.id,
                ordnungszahl=position.ordnungszahl,
                description=position.description,
                raw_text=position.raw_text,
                quantity=position.quantity,
                unit=position.unit,
                billable=position.billable,
                position_type=position.position_type,
                parameters_json=position.parameters.model_dump_json() if position.parameters else None,
                source_page=position.source_page,
            )
        )
    return project


def _store_uploaded_pdf(content_hash: str, data: bytes) -> str | None:
    if os.getenv("VERCEL") == "1":
        uploads_dir = Path("/tmp/tiefbaux/uploads")
    else:
        uploads_dir = Path(settings.project_root) / "backend" / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = uploads_dir / f"{content_hash}.pdf"
    try:
        pdf_path.write_bytes(data)
    except Exception:
        logger.exception("Failed to save inbound LV attachment")
        return None
    return str(Path("uploads") / f"{content_hash}.pdf")


def _upsert_project_upload_file(
    db: Session,
    *,
    project_id: int,
    filename: str | None,
    content: bytes,
) -> None:
    existing = db.scalar(
        select(ProjectFile).where(
            ProjectFile.project_id == project_id,
            ProjectFile.kind == "upload",
        )
    )
    if existing:
        existing.filename = filename
        existing.content = content
        existing.updated_at = datetime.utcnow()
        return
    db.add(
        ProjectFile(
            project_id=project_id,
            kind="upload",
            filename=filename,
            content=content,
        )
    )


_BEDARF_KEYWORDS = (
    "bedarf",
    "bedarfsanfrage",
    "bedarfsplanung",
    "zum bedarf",
    "auftrag erhalten",
    "auftrag bekommen",
    "zuschlag erhalten",
    "zuschlag bekommen",
)


def _detect_anfrage_art(subject: str | None, body: str | None) -> str:
    """Classify an inbound LV as submission (default) vs bedarf.

    Bedarf = second submission after the Unternehmer actually won the tender;
    signalled explicitly in the Betreff or Text ("Bedarf", "Zuschlag erhalten", …).
    Default is submission (Vorab-Anfrage vor Auftragserteilung).
    """
    text = f"{subject or ''} {body or ''}".lower()
    if any(kw in text for kw in _BEDARF_KEYWORDS):
        return "bedarf"
    return "submission"


def _sender_role(db: Session, sender_email: str | None) -> str | None:
    """Look up whether the sender is a known customer or supplier.

    Customer match is by Kunde.email_domain (customers share a company domain).
    Supplier match is by exact Supplier.email. Returns "customer", "supplier",
    or None.
    """
    if not sender_email:
        return None
    addr = sender_email.strip().lower()
    if "@" not in addr:
        return None
    domain = addr.split("@", 1)[1]
    kunde_hit = db.scalar(select(Kunde.id).where(func.lower(Kunde.email_domain) == domain))
    if kunde_hit is not None:
        return "customer"
    supplier_hit = db.scalar(select(Supplier.id).where(func.lower(Supplier.email) == addr))
    if supplier_hit is not None:
        return "supplier"
    return None


def _classify_email(
    subject: str,
    body: str,
    attachments: list[_Attachment],
    sender_role: str | None = None,
) -> str:
    attachment_names = " ".join(att.filename for att in attachments if att.filename)
    text = f"{subject}\n{body}\n{attachment_names}".lower()
    has_pdf = any(att.is_pdf for att in attachments)
    has_offer_keyword = any(keyword.lower() in text for keyword in settings.inbound_email_offer_keywords)
    has_new_lv_keyword = any(keyword.lower() in text for keyword in settings.inbound_email_new_lv_keywords)
    has_non_lv_pdf_hint = any(hint in text for hint in _NON_LV_PDF_HINTS)
    has_lv_pdf_hint = any(hint in text for hint in _LV_PDF_HINTS)
    has_ref = "tbx-inq" in text or "tbx-proj" in text

    if sender_role == "customer" and has_pdf and not has_non_lv_pdf_hint:
        return "new_lv"
    if has_ref:
        return "offer"
    if has_pdf and has_new_lv_keyword and not has_non_lv_pdf_hint:
        return "new_lv"
    if has_offer_keyword:
        return "offer"
    if not has_pdf:
        return "ignored"
    if has_non_lv_pdf_hint and not has_new_lv_keyword:
        return "ignored"
    if has_new_lv_keyword or has_lv_pdf_hint:
        return "new_lv"
    return "ignored"


def _load_pending_inquiries_for_offer(
    db: Session,
    sender_email: str,
    sender_email_hints: set[str],
    project_id_hints: set[int],
    refs_by_inquiry: set[int],
    refs_by_project_oz: set[tuple[int, str]],
    ordnungszahlen: set[str],
) -> list[SupplierInquiry]:
    if refs_by_inquiry:
        rows = db.execute(select(SupplierInquiry).where(SupplierInquiry.id.in_(refs_by_inquiry))).scalars().all()
        return [row for row in rows if row.status in PENDING_INQUIRY_STATUSES]

    query = select(SupplierInquiry).where(SupplierInquiry.status.in_(PENDING_INQUIRY_STATUSES))

    hint_emails = {email.lower() for email in sender_email_hints if email}
    if sender_email:
        hint_emails.add(sender_email.lower())
    supplier_ids = set(
        db.execute(select(Supplier.id).where(func.lower(Supplier.email).in_(hint_emails))).scalars().all()
    ) if hint_emails else set()
    if supplier_ids:
        query = query.where(SupplierInquiry.supplier_id.in_(supplier_ids))

    project_ids = set(project_id_hints) | {project_id for project_id, _ in refs_by_project_oz}
    oz_from_refs = {oz for _, oz in refs_by_project_oz}
    all_oz = set(ordnungszahlen) | oz_from_refs

    if not supplier_ids and not project_ids and not all_oz:
        return []

    if project_ids:
        query = query.where(SupplierInquiry.project_id.in_(project_ids))
    if all_oz:
        query = query.where(SupplierInquiry.ordnungszahl.in_(all_oz))

    return db.execute(query).scalars().all()


def _score_inquiry_candidate(
    inquiry: SupplierInquiry,
    supplier_id_hints: set[int],
    project_id_hints: set[int],
    corpus_tokens: set[str],
) -> int:
    score = 0
    if inquiry.supplier_id in supplier_id_hints:
        score += 35
    if inquiry.project_id is not None and inquiry.project_id in project_id_hints:
        score += 25
    if inquiry.sent_at is not None:
        age_days = (datetime.utcnow() - inquiry.sent_at).days
        if age_days <= 21:
            score += 12
        elif age_days > 90:
            score -= 8
    if inquiry.product_description:
        desc_tokens = _tokenize(inquiry.product_description)
        overlap = len(desc_tokens & corpus_tokens)
        score += min(18, overlap * 3)
    return score


def _select_best_inquiries_for_offer(
    inquiries: list[SupplierInquiry],
    ordnungszahlen: set[str],
    supplier_id_hints: set[int],
    project_id_hints: set[int],
    corpus_tokens: set[str],
    refs_by_inquiry: set[int],
) -> list[SupplierInquiry]:
    if not inquiries:
        return []
    if refs_by_inquiry:
        return inquiries

    selected_ids: set[int] = set()
    by_oz: dict[str, list[SupplierInquiry]] = {}
    for inquiry in inquiries:
        if inquiry.ordnungszahl:
            by_oz.setdefault(inquiry.ordnungszahl, []).append(inquiry)

    for oz in ordnungszahlen:
        candidates = by_oz.get(oz, [])
        if not candidates:
            continue
        # Safety first: if multiple supplier requests exist for the same OZ and
        # no supplier-level hint/reference is present, do not auto-assign.
        if len(candidates) > 1 and not supplier_id_hints:
            continue
        ranked = sorted(
            candidates,
            key=lambda inquiry: _score_inquiry_candidate(
                inquiry, supplier_id_hints, project_id_hints, corpus_tokens
            ),
            reverse=True,
        )
        best = ranked[0]
        best_score = _score_inquiry_candidate(best, supplier_id_hints, project_id_hints, corpus_tokens)
        if len(ranked) > 1:
            second_score = _score_inquiry_candidate(ranked[1], supplier_id_hints, project_id_hints, corpus_tokens)
            # If matching is highly ambiguous and no hard hint exists, skip for safety.
            if best_score - second_score < 8 and not supplier_id_hints and not project_id_hints:
                continue
        if best_score < 5 and not supplier_id_hints and not project_id_hints:
            continue
        selected_ids.add(best.id)

    if not ordnungszahlen and inquiries:
        # Without OZ and without supplier hints, only auto-assign when exactly one
        # pending inquiry exists.
        if len(inquiries) > 1 and not supplier_id_hints:
            return []
        ranked = sorted(
            inquiries,
            key=lambda inquiry: _score_inquiry_candidate(
                inquiry, supplier_id_hints, project_id_hints, corpus_tokens
            ),
            reverse=True,
        )
        best = ranked[0]
        best_score = _score_inquiry_candidate(best, supplier_id_hints, project_id_hints, corpus_tokens)
        second_score = _score_inquiry_candidate(
            ranked[1], supplier_id_hints, project_id_hints, corpus_tokens
        ) if len(ranked) > 1 else -1

        # Conservative fallback when no OZ is present.
        if best_score >= 14 and (len(ranked) == 1 or best_score - second_score >= 5):
            selected_ids.add(best.id)

    if not selected_ids and len(inquiries) == 1:
        selected_ids.add(inquiries[0].id)

    return [inquiry for inquiry in inquiries if inquiry.id in selected_ids]


def _is_outbound_demo_copy(subject: str, sender_email: str, body: str, attachments: list[_Attachment]) -> bool:
    if not settings.smtp_demo_mode:
        return False
    if attachments:
        return False
    subject_lower = (subject or "").strip().lower()
    body_lower = (body or "").lower()
    sender_lower = (sender_email or "").lower()
    smtp_from_lower = (settings.smtp_from_email or "").lower()
    return (
        sender_lower == smtp_from_lower
        and subject_lower.startswith("[demo] anfrage:")
        and "[demo-weiterleitung]" in body_lower
    )


def _store_offer_attachments(
    project_id: int | None,
    inquiry_id: int,
    attachments: list[_Attachment],
    received_at: datetime | None,
) -> list[str]:
    if not attachments:
        return []
    base_dir = Path(settings.project_root) / "backend" / "incoming_offers"
    if project_id is not None:
        base_dir = base_dir / f"project-{project_id}"
    else:
        base_dir = base_dir / "project-unassigned"
    base_dir = base_dir / f"inquiry-{inquiry_id}"
    base_dir.mkdir(parents=True, exist_ok=True)

    stamp = (received_at or datetime.utcnow()).strftime("%Y%m%d-%H%M%S")
    stored_paths: list[str] = []
    for index, attachment in enumerate(attachments, start=1):
        filename = f"{stamp}-{index:02d}-{_safe_filename(attachment.filename)}"
        target = base_dir / filename
        try:
            target.write_bytes(attachment.payload)
            stored_paths.append(str(target))
        except Exception:
            logger.exception("Failed to store inbound offer attachment: %s", filename)
    return stored_paths


def _handle_new_lv_email(
    db: Session,
    subject: str,
    attachments: list[_Attachment],
    sender_email: str | None = None,
    body: str | None = None,
) -> dict[str, object]:
    from .archive_resolvers import (
        resolve_or_create_objekt,
        resolve_or_create_kunde,
    )

    created_project_ids: list[int] = []
    skipped_hashes: list[str] = []
    errors: list[str] = []
    anfrage_art = _detect_anfrage_art(subject, body)

    for attachment in attachments:
        if not attachment.is_pdf:
            continue
        pdf_bytes = attachment.payload
        if not pdf_bytes:
            continue
        content_hash = hashlib.sha256(pdf_bytes).hexdigest()

        # We need the Objekt + Kunde identity BEFORE we can detect a duplicate
        # on the (objekt_id, kunde_id, content_hash) composite. Parse the LV
        # first so we have the metadata for Objekt resolution.
        metadata = ProjectMetadata()
        try:
            if settings.gemini_api_key:
                positions, metadata = parse_lv_with_llm(pdf_bytes)
            else:
                positions = _fallback_parse(pdf_bytes)
        except Exception as exc:
            logger.warning("Inbound LV parse via LLM failed, fallback regex parse: %s", exc)
            try:
                positions = _fallback_parse(pdf_bytes)
            except Exception as fallback_exc:
                errors.append(f"{attachment.filename}: {fallback_exc}")
                continue

        # Duplicate check: same (Objekt, Kunde, content_hash) = wirklich identisch.
        # Gleicher Hash unter einem anderen Kunden = neuer Kundenordner (NICHT skippen).
        tentative_objekt = resolve_or_create_objekt(
            db,
            bauvorhaben=metadata.bauvorhaben,
            objekt_nr=metadata.objekt_nr,
            auftraggeber=metadata.auftraggeber,
            submission_date=metadata.submission_date,
        )
        tentative_kunde = resolve_or_create_kunde(
            db,
            name=metadata.kunde_name or metadata.auftraggeber,
            sender_email=sender_email,
            address=metadata.kunde_adresse,
        )
        db.flush()
        existing = db.scalar(
            select(LVProject).where(
                LVProject.content_hash == content_hash,
                LVProject.objekt_id == tentative_objekt.id,
                LVProject.kunde_id == tentative_kunde.id,
                LVProject.anfrage_art == anfrage_art,
            )
        )
        if existing:
            skipped_hashes.append(content_hash[:12])
            continue

        pdf_path = _store_uploaded_pdf(content_hash, pdf_bytes)
        project = _store_new_project(
            db=db,
            content_hash=content_hash,
            filename=attachment.filename,
            positions=positions,
            metadata=metadata,
            pdf_path=pdf_path,
            fallback_project_name=subject[:255] if subject else None,
            sender_email=sender_email,
            anfrage_art=anfrage_art,
        )
        _upsert_project_upload_file(
            db,
            project_id=project.id,
            filename=attachment.filename or f"{content_hash}.pdf",
            content=pdf_bytes,
        )
        created_project_ids.append(project.id)

    return {
        "created_project_ids": created_project_ids,
        "skipped_hashes": skipped_hashes,
        "errors": errors,
    }


def _match_parsed_positions_to_inquiries(
    parsed_positions: list[ParsedOfferPosition],
    candidate_inquiries: list[SupplierInquiry],
) -> list[tuple[ParsedOfferPosition, SupplierInquiry | None]]:
    """Match Gemini-parsed offer positions to pending inquiries.

    Priority: exact OZ match > description token overlap > single-inquiry fallback.
    """
    inq_by_oz: dict[str, SupplierInquiry] = {}
    for inq in candidate_inquiries:
        if inq.ordnungszahl:
            inq_by_oz[inq.ordnungszahl] = inq

    used_inquiry_ids: set[int] = set()
    results: list[tuple[ParsedOfferPosition, SupplierInquiry | None]] = []

    for pos in parsed_positions:
        matched: SupplierInquiry | None = None

        # 1. Exact OZ match
        if pos.ordnungszahl and pos.ordnungszahl in inq_by_oz:
            candidate = inq_by_oz[pos.ordnungszahl]
            if candidate.id not in used_inquiry_ids:
                matched = candidate

        # 2. Description token overlap
        if matched is None and pos.article_name:
            pos_tokens = _tokenize(pos.article_name)
            best_score = 0
            for inq in candidate_inquiries:
                if inq.id in used_inquiry_ids:
                    continue
                inq_tokens = _tokenize(inq.product_description or "")
                overlap = len(pos_tokens & inq_tokens)
                if overlap > best_score:
                    best_score = overlap
                    matched = inq
            if best_score < 2:
                matched = None

        # 3. Single-inquiry fallback (if only one candidate left)
        if matched is None:
            remaining = [inq for inq in candidate_inquiries if inq.id not in used_inquiry_ids]
            if len(remaining) == 1:
                matched = remaining[0]

        if matched is not None:
            used_inquiry_ids.add(matched.id)
        results.append((pos, matched))

    return results


def _handle_offer_email(
    db: Session,
    subject: str,
    sender_email: str,
    body: str,
    sent_at: datetime | None,
    attachments: list[_Attachment],
) -> dict[str, object]:
    # ── Step 1: Build corpus from all sources (for reference parsing + fallback) ──
    attachment_texts: list[str] = []
    pdf_attachments: list[_Attachment] = []
    for attachment in attachments:
        if attachment.is_pdf:
            pdf_attachments.append(attachment)
            pdf_text = _extract_pdf_text(attachment.payload)
            if pdf_text:
                attachment_texts.append(pdf_text)
            continue
        if attachment.content_type.startswith("text/"):
            try:
                attachment_texts.append(attachment.payload.decode("utf-8", errors="replace"))
            except Exception:
                pass

    corpus = _normalize_text("\n\n".join([subject, body, *attachment_texts]))
    corpus_tokens = _tokenize(corpus)
    sender_email_hints = _extract_candidate_supplier_emails(sender_email, corpus)
    refs_by_inquiry = {int(match) for match in _INQ_REF_PATTERN.findall(corpus)}
    refs_by_project_oz = {
        (int(project_id), oz)
        for project_id, oz in _PROJ_OZ_REF_PATTERN.findall(corpus)
    }
    raw_ordnungszahlen = set(_OZ_PATTERN.findall(corpus))
    project_id_hints = {project_id for project_id, _ in refs_by_project_oz}
    if not project_id_hints:
        project_id_hints = _infer_project_id_hints_from_corpus(db, corpus_tokens)
    supplier_id_hints = set(
        db.execute(
            select(Supplier.id).where(func.lower(Supplier.email).in_(sender_email_hints))
        ).scalars().all()
    ) if sender_email_hints else set()

    # ── Step 2: Load candidate inquiries ──
    candidate_inquiries = _load_pending_inquiries_for_offer(
        db=db,
        sender_email=sender_email,
        sender_email_hints=sender_email_hints,
        project_id_hints=project_id_hints,
        refs_by_inquiry=refs_by_inquiry,
        refs_by_project_oz=refs_by_project_oz,
        ordnungszahlen=set(),
    )
    candidate_ordnungszahlen = {inq.ordnungszahl for inq in candidate_inquiries if inq.ordnungszahl}
    ordnungszahlen = {oz for oz in raw_ordnungszahlen if oz in candidate_ordnungszahlen}
    if ordnungszahlen:
        candidate_inquiries = [inq for inq in candidate_inquiries if inq.ordnungszahl in ordnungszahlen]

    inquiries = _select_best_inquiries_for_offer(
        inquiries=candidate_inquiries,
        ordnungszahlen=ordnungszahlen,
        supplier_id_hints=supplier_id_hints,
        project_id_hints=project_id_hints,
        corpus_tokens=corpus_tokens,
        refs_by_inquiry=refs_by_inquiry,
    )

    # ── Step 3: Try Gemini-based parsing (email body + PDFs in one request) ──
    gemini_positions: list[ParsedOfferPosition] = []
    try:
        pdf_payloads = [att.payload for att in pdf_attachments]
        parsed = parse_offer_with_gemini(
            email_subject=subject,
            email_body=body,
            pdf_attachments=pdf_payloads if pdf_payloads else None,
        )
        if parsed:
            logger.info("Gemini parsed %d positions from offer email (body + %d PDFs)", len(parsed), len(pdf_payloads))
            gemini_positions = parsed
    except Exception as exc:
        logger.warning("Gemini offer parse failed, falling back to regex: %s", exc)

    matched_ids: list[int] = []
    unmatched_oz = sorted(ordnungszahlen)
    touched_project_ids: set[int] = set()

    # ── Step 4a: Gemini succeeded — use structured positions ──
    if gemini_positions:
        matches = _match_parsed_positions_to_inquiries(gemini_positions, inquiries)

        # Determine supplier_id from hints or matched inquiries
        supplier_id: int | None = next(iter(supplier_id_hints), None)
        first_matched_inq = next((inq for _, inq in matches if inq is not None), None)
        if supplier_id is None and first_matched_inq:
            supplier_id = first_matched_inq.supplier_id

        for pos, matched_inquiry in matches:
            project_id = matched_inquiry.project_id if matched_inquiry else (
                next(iter(project_id_hints), None)
            )

            offer = SupplierOffer(
                inquiry_id=matched_inquiry.id if matched_inquiry else None,
                supplier_id=supplier_id or 0,
                project_id=project_id,
                position_id=matched_inquiry.position_id if matched_inquiry else None,
                ordnungszahl=pos.ordnungszahl or (matched_inquiry.ordnungszahl if matched_inquiry else None),
                article_name=pos.article_name,
                article_number=pos.article_number,
                unit_price=pos.unit_price,
                total_price=pos.total_price,
                delivery_days=pos.delivery_days,
                quantity=pos.quantity,
                unit=pos.unit,
                notes=pos.notes or f"Auto-Import (Gemini): {sender_email or 'unbekannt'} — {subject or '—'}",
                source="pdf_import",
            )
            db.add(offer)

            if matched_inquiry:
                matched_inquiry.status = "angebot_erhalten"
                matched_inquiry.updated_at = datetime.utcnow()
                matched_ids.append(matched_inquiry.id)
                if matched_inquiry.ordnungszahl in ordnungszahlen:
                    unmatched_oz = [oz for oz in unmatched_oz if oz != matched_inquiry.ordnungszahl]
                if matched_inquiry.project_id:
                    touched_project_ids.add(matched_inquiry.project_id)

            if project_id:
                touched_project_ids.add(project_id)

    # ── Step 4b: Gemini failed or returned nothing — regex fallback ──
    else:
        price_hint = _parse_price(corpus)
        delivery_hint = _parse_delivery_hint(corpus)

        for inquiry in inquiries:
            offer_text = _extract_offer_text_for_oz(corpus, inquiry.ordnungszahl)
            if offer_text:
                inquiry.product_description = offer_text
            notes: list[str] = []
            if inquiry.notes:
                notes.append(inquiry.notes.strip())
            notes.append(
                f"Automatisch aus E-Mail übernommen ({(sent_at or datetime.utcnow()).strftime('%d.%m.%Y %H:%M')})"
            )
            notes.append(f"Absender: {sender_email or 'unbekannt'}")
            notes.append(f"Betreff: {subject or '—'}")
            if price_hint is not None:
                notes.append(f"Angebotspreis-Hinweis: {price_hint:.2f} EUR")
            if delivery_hint:
                notes.append(f"Lieferzeit-Hinweis: {delivery_hint}")
            stored_paths = _store_offer_attachments(inquiry.project_id, inquiry.id, attachments, sent_at)
            if stored_paths:
                notes.append("Anhänge:")
                notes.extend(f"- {path}" for path in stored_paths)
            inquiry.notes = "\n".join(notes).strip()
            inquiry.status = "angebot_erhalten"

            offer = SupplierOffer(
                inquiry_id=inquiry.id,
                supplier_id=inquiry.supplier_id,
                project_id=inquiry.project_id,
                position_id=inquiry.position_id,
                ordnungszahl=inquiry.ordnungszahl,
                article_name=offer_text or inquiry.product_description,
                unit_price=price_hint,
                delivery_days=int(delivery_hint.split()[0]) if delivery_hint and delivery_hint.split()[0].isdigit() else None,
                quantity=inquiry.quantity,
                unit=inquiry.unit,
                notes=f"Auto-Import (Regex): {sender_email or 'unbekannt'} — {subject or '—'}",
                source="email_auto",
            )
            db.add(offer)

            matched_ids.append(inquiry.id)
            if inquiry.ordnungszahl in ordnungszahlen:
                unmatched_oz = [oz for oz in unmatched_oz if oz != inquiry.ordnungszahl]
            if inquiry.project_id:
                touched_project_ids.add(inquiry.project_id)

    # ── Step 5: Update project statuses ──
    for project_id in touched_project_ids:
        _refresh_project_status(project_id, db)

    return {
        "matched_inquiry_ids": matched_ids,
        "unmatched_ordnungszahlen": unmatched_oz,
        "gemini_positions_parsed": len(gemini_positions),
        "candidate_inquiries": [inquiry.id for inquiry in candidate_inquiries],
        "selected_inquiries": [inquiry.id for inquiry in inquiries],
        "project_id_hints": sorted(list(project_id_hints)),
        "supplier_id_hints": sorted(list(supplier_id_hints)),
    }


def _build_message_key(subject: str, sender_email: str, body: str, message_id: str | None) -> str:
    if message_id and message_id.strip():
        return message_id.strip()
    digest = hashlib.sha256(f"{subject}|{sender_email}|{body[:500]}".encode("utf-8", errors="ignore")).hexdigest()
    return f"fallback-{digest}"


def _persist_event(
    db: Session,
    message_key: str,
    mailbox: str,
    sender_email: str,
    subject: str,
    category: str,
    result: dict[str, object],
) -> None:
    event = InboundEmailEvent(
        message_id=message_key,
        mailbox=mailbox,
        sender=sender_email or None,
        subject=subject or None,
        category=category,
        result_json=json.dumps(result),
    )
    db.add(event)


def _process_message(
    db: Session,
    mailbox: str,
    msg: Message,
) -> dict[str, object]:
    subject, sender_email, body, sent_at, message_id, attachments = _extract_message_content(msg)
    message_key = _build_message_key(subject, sender_email, body, message_id)

    already_processed = db.scalar(
        select(InboundEmailEvent.id).where(InboundEmailEvent.message_id == message_key)
    )
    if already_processed:
        return {"category": "skipped", "message_id": message_key}

    role = _sender_role(db, sender_email)
    category = _classify_email(subject, body, attachments, sender_role=role)
    if category == "offer" and _is_outbound_demo_copy(subject, sender_email, body, attachments):
        category = "ignored"
        result = {"ignored": True, "reason": "outbound_demo_copy"}
        _persist_event(
            db=db,
            message_key=message_key,
            mailbox=mailbox,
            sender_email=sender_email,
            subject=subject,
            category=category,
            result=result,
        )
        return {"category": category, "message_id": message_key, **result}
    if category == "new_lv":
        result = _handle_new_lv_email(db=db, subject=subject, attachments=attachments, sender_email=sender_email, body=body)
    elif category == "offer":
        result = _handle_offer_email(
            db=db,
            subject=subject,
            sender_email=sender_email,
            body=body,
            sent_at=sent_at,
            attachments=attachments,
        )
    else:
        result = {"ignored": True, "has_attachments": bool(attachments)}

    _persist_event(
        db=db,
        message_key=message_key,
        mailbox=mailbox,
        sender_email=sender_email,
        subject=subject,
        category=category,
        result=result,
    )
    return {"category": category, "message_id": message_key, **result}


def inbox_sync_configured() -> bool:
    return bool(
        settings.inbound_email_imap_host
        and settings.inbound_email_imap_user
        and settings.inbound_email_imap_password
    )


def get_sync_status() -> dict[str, object]:
    return dict(_sync_state)


def sync_inbound_mailbox(
    db: Session,
    max_messages: int = 20,
    force_mark_seen: bool | None = None,
) -> dict[str, object]:
    if not settings.inbound_email_enabled:
        return {"status": "disabled", "detail": "INBOUND_EMAIL_ENABLED=false"}
    if not inbox_sync_configured():
        return {"status": "not_configured", "detail": "IMAP Zugangsdaten fehlen"}

    if not _sync_lock.acquire(blocking=False):
        return {"status": "already_running"}

    started_at = datetime.utcnow()
    _sync_state["running"] = True
    _sync_state["last_started_at"] = started_at.isoformat()

    summary: dict[str, object] = {
        "status": "ok",
        "mailbox": settings.inbound_email_imap_folder,
        "processed_count": 0,
        "ignored_count": 0,
        "new_lv_created": 0,
        "new_lv_skipped": 0,
        "offers_matched": 0,
        "offers_unmatched": 0,
        "errors": [],
    }

    mark_seen = settings.inbound_email_mark_seen if force_mark_seen is None else force_mark_seen
    imap: imaplib.IMAP4 | None = None
    try:
        if settings.inbound_email_imap_use_ssl:
            imap = imaplib.IMAP4_SSL(settings.inbound_email_imap_host, settings.inbound_email_imap_port)
        else:
            imap = imaplib.IMAP4(settings.inbound_email_imap_host, settings.inbound_email_imap_port)
        imap.login(settings.inbound_email_imap_user, settings.inbound_email_imap_password)
        imap.select(settings.inbound_email_imap_folder)

        status, data = imap.search(None, "UNSEEN")
        if status != "OK":
            return {"status": "error", "detail": "IMAP search failed"}
        message_ids = (data[0] or b"").split()
        if max_messages > 0:
            message_ids = message_ids[-max_messages:]

        for msg_num in message_ids:
            status, payload = imap.fetch(msg_num, "(RFC822)")
            if status != "OK":
                continue
            raw_bytes = b""
            for part in payload:
                if isinstance(part, tuple) and len(part) >= 2:
                    raw_bytes += part[1] or b""
            if not raw_bytes:
                continue

            try:
                msg = email.message_from_bytes(raw_bytes)
                result = _process_message(db, settings.inbound_email_imap_folder, msg)
                db.commit()
                summary["processed_count"] = int(summary["processed_count"]) + 1
                category = result.get("category")
                if category == "new_lv":
                    summary["new_lv_created"] = int(summary["new_lv_created"]) + len(result.get("created_project_ids", []))
                    summary["new_lv_skipped"] = int(summary["new_lv_skipped"]) + len(result.get("skipped_hashes", []))
                elif category == "offer":
                    summary["offers_matched"] = int(summary["offers_matched"]) + len(result.get("matched_inquiry_ids", []))
                    summary["offers_unmatched"] = int(summary["offers_unmatched"]) + len(result.get("unmatched_ordnungszahlen", []))
                elif category in ("ignored", "skipped"):
                    summary["ignored_count"] = int(summary["ignored_count"]) + 1
            except Exception as exc:
                db.rollback()
                logger.exception("Inbound mailbox message processing failed")
                errors = summary["errors"]
                if isinstance(errors, list):
                    errors.append(str(exc))

            if mark_seen:
                try:
                    imap.store(msg_num, "+FLAGS", "\\Seen")
                except Exception:
                    logger.warning("Failed to mark IMAP message as seen")

    except Exception as exc:
        logger.exception("Inbound mailbox sync failed")
        summary["status"] = "error"
        summary["detail"] = str(exc)
    finally:
        if imap is not None:
            try:
                imap.close()
            except Exception:
                pass
            try:
                imap.logout()
            except Exception:
                pass
        finished_at = datetime.utcnow()
        _sync_state["running"] = False
        _sync_state["last_finished_at"] = finished_at.isoformat()
        _sync_state["last_result"] = summary
        _sync_lock.release()
    return summary
