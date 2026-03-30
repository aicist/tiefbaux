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
    reference_lines: list[str] | None = None,
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

    reference_block = ""
    if reference_lines:
        joined_refs = "\n".join(f"[{line.strip()}]" for line in reference_lines if line.strip())
        if joined_refs:
            reference_block = (
                "\n\nBitte diese Referenzzeilen in der Antwort belassen "
                "(für automatische Zuordnung):\n"
                f"{joined_refs}"
            )

    body = f"""Sehr geehrte Damen und Herren,

im Rahmen des Projekts "{project_name or 'N/A'}" benötigen wir folgendes Produkt
und bitten um ein Angebot mit Preis und Lieferzeit.

Produktbeschreibung:
{product_description}

Technische Parameter:
{params_block}
{qty_str}{custom_block}{reference_block}

Mit freundlichen Grüßen,
{settings.smtp_from_name}
"""

    return subject, body


def _format_param_lines(technical_params: dict | None) -> list[str]:
    """Format technical parameters into human-readable lines."""
    if not technical_params:
        return []
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
    lines: list[str] = []
    for key, label in label_map.items():
        value = technical_params.get(key)
        if value is not None and value != "":
            if key == "nominal_diameter_dn":
                lines.append(f"  - {label}: DN {value}")
            elif key == "stiffness_class_sn":
                lines.append(f"  - {label}: SN{value}")
            else:
                lines.append(f"  - {label}: {value}")
    return lines


def build_bundled_inquiry_email(
    items: list[dict],
    project_name: str | None,
    custom_message: str | None = None,
) -> tuple[str, str]:
    """Build a single email for multiple inquiry items to the same supplier.

    Each item dict has: product_description, technical_params (dict|None),
    quantity (float|None), unit (str|None), ordnungszahl (str|None).
    """
    if len(items) == 1:
        # Single item — use the simpler format
        item = items[0]
        return build_inquiry_email(
            product_description=item["product_description"],
            project_name=project_name,
            technical_params=item.get("technical_params"),
            quantity=item.get("quantity"),
            unit=item.get("unit"),
            custom_message=custom_message,
        )

    subject = f"Sammelanfrage ({len(items)} Positionen)"
    if project_name:
        subject += f" — Projekt {project_name}"

    position_blocks: list[str] = []
    for i, item in enumerate(items, 1):
        oz = item.get("ordnungszahl")
        header = f"Position {i}" + (f" (OZ {oz})" if oz else "")
        block = f"── {header} ──\n"
        block += f"Produkt: {item['product_description']}\n"

        param_lines = _format_param_lines(item.get("technical_params"))
        if param_lines:
            block += "Technische Parameter:\n" + "\n".join(param_lines) + "\n"

        qty = item.get("quantity")
        if qty is not None:
            block += f"Menge: {qty} {item.get('unit') or 'Stück'}\n"

        position_blocks.append(block)

    positions_text = "\n".join(position_blocks)

    custom_block = ""
    if custom_message:
        custom_block = f"\n\nAnmerkung:\n{custom_message}"

    reference_lines = [
        item.get("reference_code", "").strip()
        for item in items
        if item.get("reference_code")
    ]
    reference_block = ""
    if reference_lines:
        joined_refs = "\n".join(f"[{line}]" for line in reference_lines)
        reference_block = (
            "\n\nBitte diese Referenzzeilen in der Antwort belassen "
            "(für automatische Zuordnung):\n"
            f"{joined_refs}"
        )

    body = f"""Sehr geehrte Damen und Herren,

im Rahmen des Projekts "{project_name or 'N/A'}" benötigen wir folgende Produkte
und bitten um ein Angebot mit Preis und Lieferzeit.

{positions_text}{custom_block}{reference_block}

Mit freundlichen Grüßen,
{settings.smtp_from_name}
"""

    return subject, body


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email via SMTP. Returns True if sent, False if SMTP not configured."""

    effective_recipients = [to_email]
    effective_subject = subject
    effective_body = body

    # Demo safety mode: never send to real supplier addresses.
    if settings.smtp_demo_mode and settings.smtp_demo_recipients:
        effective_recipients = settings.smtp_demo_recipients
        prefix = (settings.smtp_demo_subject_prefix or "[DEMO]").strip()
        effective_subject = f"{prefix} {subject}".strip()
        effective_body = (
            f"[Demo-Weiterleitung]\n"
            f"Original-Empfänger: {to_email}\n\n"
            f"{body}"
        )

    if not settings.smtp_host or not settings.smtp_from_email:
        logger.warning(
            "SMTP nicht konfiguriert — E-Mail wird nur gespeichert, nicht versendet. "
            "Empfänger: %s, Betreff: %s",
            to_email,
            subject,
        )
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = effective_subject
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = ", ".join(effective_recipients)

    try:
        if settings.smtp_use_tls:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)
            server.starttls()
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15)

        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)

        server.sendmail(settings.smtp_from_email, effective_recipients, msg.as_string())
        server.quit()
        logger.info("E-Mail gesendet an %s (original: %s): %s", effective_recipients, to_email, effective_subject)
        return True
    except Exception:
        logger.exception("Fehler beim E-Mail-Versand an %s", to_email)
        return False
