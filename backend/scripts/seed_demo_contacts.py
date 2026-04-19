"""One-shot: align Supplier and Kunde contact addresses for the demo.

Usage:
    python3 scripts/seed_demo_contacts.py [supplier_email] [customer_domain]

Defaults:
    supplier_email   = "mirco@getaicist.de"
    customer_domain  = "aicist.de"

Demo mailbox layout:
    - mirco@tryaicist.de      → Fassbender (app SMTP+IMAP)
    - mirco@getaicist.de      → Lieferanten-Rolle (alle Supplier-Mails landen hier)
    - mircobertram@aicist.de  → Kunden-Rolle (schickt LV-Anfragen, empfängt Angebot)

Every supplier record gets ``email = supplier_email``. The Kunde has no direct
email column — only ``email_domain``, which is aligned to ``customer_domain``
so the offer dialog prefills the customer recipient from inbound events.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Kunde, Supplier


def main(supplier_email: str, customer_domain: str) -> None:
    with SessionLocal() as db:
        suppliers = db.scalars(select(Supplier)).all()
        for s in suppliers:
            s.email = supplier_email
        kunden = db.scalars(select(Kunde)).all()
        for k in kunden:
            k.email_domain = customer_domain
        db.commit()
        print(
            f"Rewrote {len(suppliers)} supplier(s) to {supplier_email} "
            f"and {len(kunden)} kunde(n) to domain {customer_domain}."
        )


if __name__ == "__main__":
    supplier = sys.argv[1] if len(sys.argv) > 1 else "mirco@getaicist.de"
    domain = sys.argv[2] if len(sys.argv) > 2 else "aicist.de"
    main(supplier, domain)
