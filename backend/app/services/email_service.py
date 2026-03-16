from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText

from ..config import settings

logger = logging.getLogger(__name__)


def build_inquiry_email(
    product_description: str,
    project_name: str | None,
    technical_params: dict | None,
    quantity: float | None,
    unit: str | None,
    custom_message: str | None = None,
) -> tuple[str, str]:
    """Build subject and body for a supplier inquiry email."""

    subject = f"Anfrage: {product_description[:80]}"
    if project_name:
        subject += f" — Projekt {project_name}"

    # Build parameter lines
    param_lines: list[str] = []
    if technical_params:
        label_map = {
            "nominal_diameter_dn": "Nennweite",
            "material": "Werkstoff",
            "load_class": "Belastungsklasse",
            "dimensions": "Abmessungen",
            "norm": "Norm",
            "stiffness_class_sn": "Steifigkeitsklasse",
            "reference_product": "Referenzprodukt",
            "installation_area": "Einbaubereich",
            "product_category": "Produktkategorie",
        }
        for key, label in label_map.items():
            value = technical_params.get(key)
            if value is not None and value != "":
                if key == "nominal_diameter_dn":
                    param_lines.append(f"  - {label}: DN {value}")
                elif key == "stiffness_class_sn":
                    param_lines.append(f"  - {label}: SN{value}")
                else:
                    param_lines.append(f"  - {label}: {value}")

    params_block = "\n".join(param_lines) if param_lines else "  (keine weiteren Angaben)"

    qty_str = ""
    if quantity is not None:
        qty_str = f"\nMenge: {quantity} {unit or 'Stück'}"

    custom_block = ""
    if custom_message:
        custom_block = f"\n\nAnmerkung:\n{custom_message}"

    body = f"""Sehr geehrte Damen und Herren,

im Rahmen des Projekts "{project_name or 'N/A'}" benötigen wir folgendes Produkt
und bitten um ein Angebot mit Preis und Lieferzeit.

Produktbeschreibung:
{product_description}

Technische Parameter:
{params_block}
{qty_str}{custom_block}

Mit freundlichen Grüßen,
{settings.smtp_from_name}
"""

    return subject, body


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email via SMTP. Returns True if sent, False if SMTP not configured."""

    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning(
            "SMTP nicht konfiguriert — E-Mail wird nur gespeichert, nicht versendet. "
            "Empfänger: %s, Betreff: %s",
            to_email,
            subject,
        )
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email

    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(settings.smtp_from_email, [to_email], msg.as_string())
        server.quit()
        logger.info("E-Mail gesendet an %s: %s", to_email, subject)
        return True
    except Exception:
        logger.exception("Fehler beim E-Mail-Versand an %s", to_email)
        return False
