from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Product, Supplier


ARTICLE_CSV_NAME = "TiefbauX_Dummy_Datenbank_v2.xlsx - Artikel.csv"


NUMERIC_FLOAT_FIELDS = {
    "ek_netto",
    "vk_listenpreis_netto",
    "staffelpreis_ab_10",
    "staffelpreis_ab_50",
    "staffelpreis_ab_100",
    "wandstaerke_mm",
    "gewicht_kg",
}

NUMERIC_INT_FIELDS = {
    "nennweite_dn",
    "nennweite_od",
    "laenge_mm",
    "breite_mm",
    "hoehe_mm",
    "lager_rheinbach",
    "lager_duesseldorf",
    "lager_gesamt",
    "lieferant_1_lieferzeit_tage",
}


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip().replace(" ", "")
    if not text:
        return None

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    parsed = _to_float(value)
    if parsed is None:
        return None
    return int(round(parsed))


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text if text else None


def _csv_path() -> Path:
    return settings.project_root / ARTICLE_CSV_NAME


def seed_products_if_empty(db: Session) -> int:
    existing = db.scalar(select(Product.id).limit(1))
    if existing is not None:
        return db.query(Product).count()

    csv_path = _csv_path()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    products: list[Product] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            product_kwargs: dict[str, object | None] = {}

            for field in Product.__table__.columns.keys():
                if field == "id":
                    continue

                value = row.get(field)
                if field in NUMERIC_FLOAT_FIELDS:
                    product_kwargs[field] = _to_float(value)
                elif field in NUMERIC_INT_FIELDS:
                    product_kwargs[field] = _to_int(value)
                else:
                    product_kwargs[field] = _normalize_text(value)

            products.append(Product(**product_kwargs))

    db.bulk_save_objects(products)
    db.commit()
    return len(products)


_DEFAULT_SUPPLIERS = [
    {
        "name": "Wavin GmbH",
        "email": "anfragen@wavin.com",
        "phone": "+49 2831 1340",
        "categories": '["Kanalrohre","Formstuecke","Schachtbauteile","Hausanschluss","Kabelschutz","Dichtungen & Zubehoer"]',
    },
    {
        "name": "ACO Tiefbau",
        "email": "anfragen@aco.de",
        "phone": "+49 4621 3810",
        "categories": '["Strassenentwässerung","Rinnen","Schachtabdeckungen"]',
    },
    {
        "name": "Kann Baustoffwerke",
        "email": "anfragen@kann.de",
        "phone": "+49 2622 7070",
        "categories": '["Pflastersteine","Bordsteine","Schachtbauteile"]',
    },
    {
        "name": "Rehau AG",
        "email": "anfragen@rehau.com",
        "phone": "+49 9283 770",
        "categories": '["Kanalrohre","Formstuecke","Hausanschluss"]',
    },
    {
        "name": "Funke Kunststoffe GmbH",
        "email": "anfragen@funke.de",
        "phone": "+49 5731 2500",
        "categories": '["Kanalrohre","Schachtbauteile","Formstuecke"]',
    },
    {
        "name": "Mönninghoff GmbH",
        "email": "anfragen@moenninghoff.de",
        "phone": "+49 251 97400",
        "categories": '["Kabelschutz"]',
    },
]


def seed_suppliers_if_empty(db: Session) -> int:
    existing = db.scalar(select(Supplier.id).limit(1))
    if existing is not None:
        return db.query(Supplier).count()

    for s in _DEFAULT_SUPPLIERS:
        db.add(Supplier(
            name=s["name"],
            email=s["email"],
            phone=s.get("phone"),
            categories_json=s.get("categories"),
        ))
    db.commit()
    return len(_DEFAULT_SUPPLIERS)
