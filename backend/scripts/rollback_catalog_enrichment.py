"""Rollback unreliable catalog enrichment and restore source-backed vendor data.

Strategy:
- restore Wavin from local structured extraction JSON
- restore HAURATON from the local Excel source
- restore Muffenrohr + REHAU from their deterministic importer definitions
- clear heuristic-only technical fields for ACO, where no reliable source importer exists
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import SessionLocal
from app.models import Product
from scripts.import_hauraton_excel import (  # type: ignore
    DEFAULT_INCLUDED_FAMILIES,
    DEFAULT_SOURCE as HAURATON_SOURCE,
    _build_product as build_hauraton_product,
    _load_rows as load_hauraton_rows,
)
from scripts.import_muffenrohr_kg import run_import as run_muffenrohr_kg_import  # type: ignore
from scripts.import_muffenrohr_pp import run_import as run_muffenrohr_pp_import  # type: ignore
from scripts.import_rehau import run_import as run_rehau_import  # type: ignore
from scripts.import_wavin_catalog import build_product as build_wavin_product  # type: ignore


ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "backend" / "tiefbaux.db"
WAVIN_JSON = Path(__file__).resolve().with_name("wavin_extracted.json")


def _backup_db() -> Path:
    backup_path = DB_PATH.with_suffix(".pre_rollback.bak")
    shutil.copy2(DB_PATH, backup_path)
    return backup_path


def _restore_wavin() -> int:
    import json

    if not WAVIN_JSON.exists():
        raise FileNotFoundError(f"Wavin source JSON not found: {WAVIN_JSON}")

    raw = json.loads(WAVIN_JSON.read_text(encoding="utf-8"))
    products = []
    for idx, item in enumerate(raw):
        product = build_wavin_product(item, idx)
        if product:
            products.append(product)

    with SessionLocal() as db:
        db.execute(delete(Product).where(Product.hersteller == "Wavin GmbH"))
        db.add_all(products)
        db.commit()
    return len(products)


def _restore_hauraton() -> int:
    rows, _stats = load_hauraton_rows(HAURATON_SOURCE, set(DEFAULT_INCLUDED_FAMILIES))
    products = [build_hauraton_product(row) for row in rows]
    with SessionLocal() as db:
        db.execute(delete(Product).where(Product.hersteller == "HAURATON"))
        db.add_all(products)
        db.commit()
    return len(products)


def _restore_muffenrohr() -> None:
    with SessionLocal() as db:
        db.execute(delete(Product).where(Product.hersteller == "Muffenrohr"))
        db.commit()
    run_muffenrohr_kg_import()
    run_muffenrohr_pp_import()


def _restore_rehau() -> None:
    with SessionLocal() as db:
        db.execute(delete(Product).where(Product.hersteller == "REHAU"))
        db.commit()
    run_rehau_import()


def _clear_aco_heuristics() -> int:
    with SessionLocal() as db:
        products = list(db.scalars(select(Product).where(Product.hersteller == "ACO")))
        changed = 0
        for product in products:
            before = (
                product.system_familie,
                product.kompatible_systeme,
                product.verbindungstyp,
                product.dichtungstyp,
                product.kompatible_dn_anschluss,
                product.werkstoff,
            )
            product.system_familie = None
            product.kompatible_systeme = None
            product.verbindungstyp = None
            product.dichtungstyp = None
            product.kompatible_dn_anschluss = None
            product.werkstoff = None
            after = (
                product.system_familie,
                product.kompatible_systeme,
                product.verbindungstyp,
                product.dichtungstyp,
                product.kompatible_dn_anschluss,
                product.werkstoff,
            )
            if before != after:
                changed += 1
        db.commit()
    return changed


def main() -> None:
    backup_path = _backup_db()
    print(f"Backup created: {backup_path}")

    wavin = _restore_wavin()
    print(f"Restored Wavin: {wavin}")

    hauraton = _restore_hauraton()
    print(f"Restored HAURATON: {hauraton}")

    _restore_muffenrohr()
    print("Restored Muffenrohr")

    _restore_rehau()
    print("Restored REHAU")

    aco_changed = _clear_aco_heuristics()
    print(f"Cleared heuristic ACO fields: {aco_changed}")


if __name__ == "__main__":
    main()
