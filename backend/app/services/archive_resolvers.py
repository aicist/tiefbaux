"""Resolver helpers for Objekt and Kunde identity.

Ein Objekt wird durch normalisierten ``bauvorhaben + objekt_nr + auftraggeber``
identifiziert; ein Kunde durch die E-Mail-Domain (primär) plus normalisierten
Firmennamen (sekundär / Fallback bei Upload ohne Mail).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Kunde, LVProject, Objekt


_SLUG_NONWORD = re.compile(r"[^a-z0-9]+")
_EMAIL_RE = re.compile(r"<([^>]+)>|([\w.+-]+@[\w.-]+\.\w+)")

# Domains that are free-mail / forwarders and not identifying a company
_GENERIC_MAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.de",
    "hotmail.com", "hotmail.de", "outlook.com", "outlook.de",
    "gmx.de", "gmx.net", "web.de", "t-online.de", "mail.de",
    "icloud.com", "me.com",
}

# Company-suffix noise we strip when normalizing customer names
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(gmbh\s*&\s*co\.?\s*kg|gmbh\s*co\.?\s*kg|gmbh|ag|kg|ohg|ug|e\.?k\.?|mbh|"
    r"bauunternehmung|baugesellschaft|bau-?\s*und\s*transporte?|tiefbau|"
    r"strassen-?\s*und\s*tiefbau|bauunternehmen)\b",
    re.IGNORECASE,
)


def _slugify(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    ascii_form = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return _SLUG_NONWORD.sub("-", ascii_form).strip("-")


def _normalize_company_name(name: str) -> str:
    if not name:
        return ""
    cleaned = _COMPANY_SUFFIX_RE.sub(" ", name)
    cleaned = re.sub(r"[.,&]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_objekt_slug(bauvorhaben: Optional[str], objekt_nr: Optional[str], auftraggeber: Optional[str]) -> str:
    parts = [
        _slugify(bauvorhaben or ""),
        _slugify(objekt_nr or ""),
        _slugify(_normalize_company_name(auftraggeber or "")),
    ]
    parts = [p for p in parts if p]
    return "|".join(parts) if parts else "unbekanntes-objekt"


def build_kunde_slug(name: Optional[str], email_domain: Optional[str]) -> str:
    """Kunde slug: domain if present and non-generic, else normalized name."""
    if email_domain and email_domain.lower() not in _GENERIC_MAIL_DOMAINS:
        return f"domain:{email_domain.lower()}"
    normalized = _normalize_company_name(name or "")
    slug = _slugify(normalized)
    return f"name:{slug}" if slug else "name:unbekannter-kunde"


def extract_email_domain(sender: Optional[str]) -> Optional[str]:
    """Parse 'Max Mustermann <max@strabag.com>' or 'max@strabag.com' → 'strabag.com'."""
    if not sender:
        return None
    m = _EMAIL_RE.search(sender)
    if not m:
        return None
    addr = m.group(1) or m.group(2)
    if not addr or "@" not in addr:
        return None
    domain = addr.split("@", 1)[1].strip().lower()
    return domain or None


def resolve_or_create_objekt(
    db: Session,
    *,
    bauvorhaben: Optional[str],
    objekt_nr: Optional[str],
    auftraggeber: Optional[str],
    submission_date: Optional[str] = None,
) -> Objekt:
    slug = build_objekt_slug(bauvorhaben, objekt_nr, auftraggeber)
    existing = db.query(Objekt).filter(Objekt.slug == slug).one_or_none()
    if existing:
        # Backfill fields that were empty at first creation
        if bauvorhaben and not existing.bauvorhaben:
            existing.bauvorhaben = bauvorhaben
        if objekt_nr and not existing.objekt_nr:
            existing.objekt_nr = objekt_nr
        if auftraggeber and not existing.auftraggeber:
            existing.auftraggeber = auftraggeber
        if submission_date and not existing.submission_date:
            existing.submission_date = submission_date
        return existing

    objekt = Objekt(
        slug=slug,
        bauvorhaben=bauvorhaben,
        objekt_nr=objekt_nr,
        auftraggeber=auftraggeber,
        submission_date=submission_date,
    )
    db.add(objekt)
    db.flush()
    return objekt


def resolve_or_create_kunde(
    db: Session,
    *,
    name: Optional[str],
    sender_email: Optional[str] = None,
    address: Optional[str] = None,
) -> Kunde:
    email_domain = extract_email_domain(sender_email)
    slug = build_kunde_slug(name, email_domain)

    existing = db.query(Kunde).filter(Kunde.slug == slug).one_or_none()
    if existing:
        if name and not existing.display_name:
            existing.display_name = name
        if email_domain and not existing.email_domain:
            existing.email_domain = email_domain
        if address and not existing.address:
            existing.address = address
        return existing

    kunde = Kunde(
        slug=slug,
        name=name or (email_domain or "Unbekannter Kunde"),
        display_name=name,
        email_domain=email_domain,
        address=address,
    )
    db.add(kunde)
    db.flush()
    return kunde


def find_shareable_project(
    db: Session,
    *,
    objekt_id: int,
    content_hash: str,
    exclude_project_id: Optional[int] = None,
) -> Optional[LVProject]:
    """Return another project under the same Objekt with the same content_hash.

    Used to copy selections/workstate when a different Kunde submits an
    identical LV for the same Objekt ("gleiche Kalkulation").
    """
    q = db.query(LVProject).filter(
        LVProject.objekt_id == objekt_id,
        LVProject.content_hash == content_hash,
    )
    if exclude_project_id is not None:
        q = q.filter(LVProject.id != exclude_project_id)
    return q.first()
