"""Import Muffenrohr PP SN 10 grün products from Preisliste 2026.

Source: muffenrohr.de PP Kanalrohre und Formstücke SN 10 grün, Stand 02/2026
nach DIN EN 14758-1
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal
from app.models import Product
from sqlalchemy import select

# ── Constants ────────────────────────────────────────────────────────

HERSTELLER = "Muffenrohr"
SYSTEM = "PP SN10 grün"
WERKSTOFF = "PP"
NORM = "DIN EN 14758-1"
WAEHRUNG = "EUR"
KATEGORIE = "Kanalrohre"
EINSATZBEREICH = "Abwasser"
STATUS = "aktiv"
SN = "SN10"


def _art_id(nr: str) -> str:
    return f"MR-{nr}"


# ── Product data ─────────────────────────────────────────────────────
# (art_nr, name, subcategory, dn, length_mm, price, unit, angle, dn_abgang)

PRODUCTS: list[tuple] = []


# ── PP Kanalrohre ──

def _add_pipe(length_mm: int, data: dict[int, tuple[str, float]]):
    length_m = length_mm / 1000
    for dn, (art, price_per_m) in data.items():
        if price_per_m is None:
            continue
        # 500mm uses Preis/Stück, others Preis/Meter
        if length_mm == 500:
            total = price_per_m  # already total
        else:
            total = round(price_per_m * length_m, 2)
        name = f"PP Kanalrohr DN{dn} SN10 grün L={length_m}m"
        PRODUCTS.append((art, name, "KG-Rohre", dn, length_mm, total, "Stk", None, None))

# 500mm (Preis/Stück)
_add_pipe(500, {
    110: ("215469", 9.40),
    125: ("215480", 13.25),
    160: ("215489", 20.45),
    200: ("307180", 37.10),
})

# 1000mm (Preis/Meter)
_add_pipe(1000, {
    110: ("215474", 14.65),
    125: ("215483", 20.90),
    160: ("215505", 30.45),
    200: ("307181", 49.25),
    250: ("513662", 111.80),
    315: ("513665", 179.55),
    400: ("617188", 316.05),
    500: ("707916", 516.00),
})

# 2000mm (Preis/Meter)
_add_pipe(2000, {
    110: ("215476", 14.20),
    125: ("215485", 18.95),
    160: ("215506", 27.55),
    200: ("389965", 46.70),
})

# 3000mm (Preis/Meter)
_add_pipe(3000, {
    110: ("1149564", 13.55),
    125: ("1152654", 18.95),
    160: ("1149563", 27.35),
    200: ("1152655", 45.40),
    250: ("513663", 76.35),
    315: ("513666", 117.20),
    400: ("617189", 204.25),
    500: ("707915", 333.25),
})

# 5000mm (Preis/Meter)
_add_pipe(5000, {
    110: ("215479", 13.35),
    125: ("215487", 18.75),
    160: ("215507", 26.90),
    200: ("307182", 44.55),
})

# 6000mm (Preis/Meter)
_add_pipe(6000, {
    250: ("513664", 70.95),
    315: ("513667", 109.65),
    400: ("617190", 184.90),
    500: ("707914", 292.40),
})


# ── PP Bogen ──

_bogen = {
    (15, 110): ("215508", 10.15),
    (15, 125): ("215518", 14.00),
    (15, 160): ("215522", 22.90),
    (15, 200): ("307184", 52.70),
    (15, 250): ("513790", 135.45),
    (15, 315): ("513792", 215.00),
    (15, 400): ("617191", 634.25),
    (15, 500): ("707913", 1118.00),

    (30, 110): ("215512", 10.25),
    (30, 125): ("215519", 14.00),
    (30, 160): ("215523", 23.15),
    (30, 200): ("597405", 55.50),
    (30, 250): ("1154163", 178.45),
    (30, 315): ("1245755", 236.50),
    (30, 400): ("1245756", 666.50),
    (30, 500): ("1036306", 1204.00),

    (45, 110): ("215514", 11.40),
    (45, 125): ("215520", 15.30),
    (45, 160): ("215525", 27.75),
    (45, 200): ("307185", 59.15),
    (45, 250): ("513791", 151.60),
    (45, 315): ("513793", 240.80),
    (45, 400): ("617192", 892.25),
    (45, 500): ("1036301", 1870.50),

    (67, 110): ("215515", 15.70),
    (67, 125): ("389969", 26.90),
    (67, 160): ("389968", 46.25),

    (87, 110): ("215517", 15.70),
    (87, 125): ("215521", 26.90),
    (87, 160): ("215527", 46.25),
    (87, 200): ("1308586", 81.70),
    (87, 250): ("1250444", 217.15),
    (87, 315): ("1245757", 322.50),
    (87, 400): ("1246178", 1204.00),
}
for (angle, dn), (art, price) in _bogen.items():
    PRODUCTS.append((art, f"PP Bogen {angle}° DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", angle, None))


# ── PP Reduktion ──

_reduktion = {
    (110, 125): ("215548", 13.80),
    (110, 160): ("215550", 21.75),
    (125, 160): ("215552", 23.25),
    (160, 200): ("389971", 53.75),
    (200, 250): ("513795", 133.30),
    (250, 315): ("513798", 285.95),
    (315, 400): ("617199", 580.50),
    (400, 500): ("707909", 999.75),
}
for (dn_abg, dn_main), (art, price) in _reduktion.items():
    PRODUCTS.append((art, f"PP Reduktion DN{dn_main}/{dn_abg} SN10 grün",
                     "Formstücke", dn_main, None, price, "Stk", None, dn_abg))


# ── PP Abzweig 45° ──

_abzweig45 = {
    (110, 110): ("215532", 21.95),
    (110, 125): ("670870", 34.40),
    (110, 160): ("215535", 36.35),
    (110, 200): ("1301609", 137.60),

    (125, 125): ("215533", 35.50),
    (125, 160): ("389970", 74.20),

    (160, 160): ("215536", 47.10),
    (160, 200): ("307186", 101.05),
    (160, 250): ("513800", 167.70),
    (160, 315): ("544967", 247.25),
    (160, 400): ("617193", 726.70),
    (160, 500): ("707912", 1591.00),

    (200, 200): ("307187", 123.65),
    (200, 250): ("513803", 378.40),
    (200, 400): ("617194", 752.50),
    (200, 500): ("1406116", 2042.50),

    (250, 250): ("513802", 436.45),

    (315, 315): ("513804", 924.50),
    (315, 400): ("1302694", 1064.25),
    (315, 500): ("1406117", 2085.50),

    (400, 400): ("617195", 1558.75),
}
for (dn_abg, dn_main), (art, price) in _abzweig45.items():
    PRODUCTS.append((art, f"PP Einfachabzweig 45° DN{dn_main}/{dn_abg} SN10 grün",
                     "Formstücke", dn_main, None, price, "Stk", 45, dn_abg))


# ── PP Abzweig 87° ──

_abzweig87 = {
    (110, 110): ("215538", 40.85),
    (110, 160): ("706361", 52.70),
    (160, 160): ("706362", 83.85),
}
for (dn_abg, dn_main), (art, price) in _abzweig87.items():
    PRODUCTS.append((art, f"PP Einfachabzweig 87° DN{dn_main}/{dn_abg} SN10 grün",
                     "Formstücke", dn_main, None, price, "Stk", 87, dn_abg))


# ── PP Anschluss an Gußrohr Spitzende ──

_anschluss_guss = {
    110: ("215628", 36.55),
    125: ("215629", None),  # auf Anfrage
    160: ("215630", None),
}
for dn, (art, price) in _anschluss_guss.items():
    if price:
        PRODUCTS.append((art, f"PP Anschluss an Gußrohr Spitzende DN{dn} SN10 grün",
                         "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Anschluss an Steinzeug-Spitzende inkl. Profilring ──

_anschluss_stz = {
    110: ("389973", 66.65),
    125: ("389974", 111.80),
    160: ("389975", 138.70),
}
for dn, (art, price) in _anschluss_stz.items():
    PRODUCTS.append((art, f"PP Anschluss an Steinzeug-Spitzende DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Anschluss an Steinzeug-Muffe ──

_anschluss_stz_muffe = {
    110: ("215631", 52.70),
    125: ("215632", None),  # auf Anfrage
    160: ("215633", 75.25),
}
for dn, (art, price) in _anschluss_stz_muffe.items():
    if price:
        PRODUCTS.append((art, f"PP Anschluss an Steinzeug-Muffe DN{dn} SN10 grün",
                         "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Anschluss an Beton ──

_anschluss_beton = {
    160: ("542744", 408.50),
    200: ("597406", 795.50),
}
for dn, (art, price) in _anschluss_beton.items():
    PRODUCTS.append((art, f"PP Anschluss an Beton DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Doppelmuffe ──

_doppelmuffe = {
    110: ("215554", 16.15),
    125: ("215559", 17.65),
    160: ("215560", 30.10),
    200: ("307190", 55.90),
    250: ("513805", 122.55),
    315: ("513806", 178.45),
    400: ("617197", 376.25),
    500: ("707910", 634.25),
}
for dn, (art, price) in _doppelmuffe.items():
    PRODUCTS.append((art, f"PP Doppelmuffe DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Überschiebmuffe ──

_ueberschiebmuffe = {
    110: ("215539", 16.35),
    125: ("215542", 17.65),
    160: ("215545", 30.10),
    200: ("307189", 55.90),
    250: ("513807", 122.55),
    315: ("513809", 178.45),
    400: ("617196", 376.25),
    500: ("707911", 623.50),
}
for dn, (art, price) in _ueberschiebmuffe.items():
    PRODUCTS.append((art, f"PP Überschiebmuffe DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Reinigungsrohr ──

_reinigung = {
    110: ("215626", 193.50),
    125: ("251281", 290.25),
    160: ("215627", 311.75),
    200: ("617703", 361.20),
}
for dn, (art, price) in _reinigung.items():
    PRODUCTS.append((art, f"PP Reinigungsrohr DN{dn} SN10 grün",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── PP Lippendichtring ──

_lippendichtring = {
    110: ("215620", 6.75),
    125: ("215624", 11.10),
    160: ("215625", 12.00),
    200: ("429256", 18.60),
    250: ("617706", 30.60),
    315: ("617707", 39.00),
    400: ("617201", 44.40),
    500: ("709311", 129.60),
}
for dn, (art, price) in _lippendichtring.items():
    PRODUCTS.append((art, f"PP Lippendichtring DN{dn}",
                     "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


# ── PP NBR-Lippendichtring Öl- und Benzinbeständig ──

_nbr_dichtring = {
    110: ("389978", 10.90),
    125: ("389979", 14.65),
    160: ("389980", 29.50),
    200: ("429255", 45.80),
    250: ("617708", 96.75),
    315: ("617709", 157.75),
    400: ("617202", 187.85),
    500: ("709310", 237.60),
}
for dn, (art, price) in _nbr_dichtring.items():
    PRODUCTS.append((art, f"PP NBR-Lippendichtring öl-/benzinbeständig DN{dn}",
                     "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


# ── PP Profilring US ──

_profilring = {
    110: ("617710", 50.55),
    125: ("617711", 109.65),
    160: ("617712", 277.35),
}
for dn, (art, price) in _profilring.items():
    PRODUCTS.append((art, f"PP Profilring US DN{dn}",
                     "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


# ── KGF-Schachtfutter PP/PUR BL 110mm ──

_schachtfutter_110 = {
    110: ("707530", 54.00),
    125: ("1022775", 60.00),
    160: ("707531", 64.50),
    200: ("707532", 82.50),
    250: ("1062443", 132.00),
    315: ("1092084", 168.00),
    400: ("1096257", 216.00),
}
for dn, (art, price) in _schachtfutter_110.items():
    PRODUCTS.append((art, f"KGF Schachtfutter PP/PUR BL 110mm DN{dn}",
                     "Schachtbauteile", dn, None, price, "Stk", None, None))


# ── KGF-Schachtfutter PP/PUR BL 240mm ──

_schachtfutter_240 = {
    110: ("707533", 60.00),
    125: ("1022776", 84.00),
    160: ("707534", 105.00),
    200: ("707535", 219.00),
    250: ("707536", 258.00),
    315: ("707537", 381.00),
    400: ("310240", 1272.00),
    500: ("389863", None),  # shown but let me check — 1.272,00 is for DN400
}
# Actually from PDF: DN400=310240/381,00  DN500=389863/1.272,00
_schachtfutter_240_corrected = {
    110: ("707533", 60.00),
    125: ("1022776", 84.00),
    160: ("707534", 105.00),
    200: ("707535", 219.00),
    250: ("707536", 258.00),
    315: ("707537", 381.00),
    400: ("310240", 381.00),
    500: ("389863", 1272.00),
}
for dn, (art, price) in _schachtfutter_240_corrected.items():
    PRODUCTS.append((art, f"KGF Schachtfutter PP/PUR BL 240mm DN{dn}",
                     "Schachtbauteile", dn, None, price, "Stk", None, None))


# ── Import logic ─────────────────────────────────────────────────────

def run_import():
    db = SessionLocal()
    try:
        existing = set(
            db.scalars(
                select(Product.artikel_id).where(Product.hersteller == HERSTELLER)
            ).all()
        )
        print(f"Existing {HERSTELLER} products in DB: {len(existing)}")

        added = 0
        skipped = 0
        for entry in PRODUCTS:
            art_nr, name, subcategory, dn, length_mm, price, unit, angle, dn_abgang = entry
            if not art_nr or price is None:
                skipped += 1
                continue

            artikel_id = _art_id(art_nr)
            if artikel_id in existing:
                skipped += 1
                continue

            product = Product(
                artikel_id=artikel_id,
                hersteller=HERSTELLER,
                hersteller_artikelnr=art_nr,
                artikelname=name,
                artikelbeschreibung=name,
                kategorie=KATEGORIE,
                unterkategorie=subcategory,
                werkstoff=WERKSTOFF,
                nennweite_dn=dn,
                laenge_mm=length_mm,
                steifigkeitsklasse_sn=SN,
                norm_primaer=NORM,
                system_familie=SYSTEM,
                einsatzbereich=EINSATZBEREICH,
                vk_listenpreis_netto=round(price, 2),
                waehrung=WAEHRUNG,
                preiseinheit=unit,
                status=STATUS,
            )

            if dn_abgang and dn_abgang != dn:
                product.kompatible_dn_anschluss = str(dn_abgang)

            db.add(product)
            existing.add(artikel_id)
            added += 1

        db.commit()
        print(f"Import complete: {added} added, {skipped} skipped")
        print(f"Total {HERSTELLER} products now: {len(existing)}")

    finally:
        db.close()


if __name__ == "__main__":
    run_import()
