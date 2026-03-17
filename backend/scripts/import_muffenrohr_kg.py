"""Import Muffenrohr KG PVC-U SN 4 products from Preisliste 2026.

Source: muffenrohr.de KG – PVC-U-KANALROHRE SN 4, Stand 01/2026
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
SYSTEM = "KG PVC-U"
WERKSTOFF = "PVC-U"
NORM = "DIN EN 1401"
WAEHRUNG = "EUR"
KATEGORIE = "Kanalrohre"
EINSATZBEREICH = "Abwasser"
STATUS = "aktiv"
SN = "SN4"


def _art_id(nr: str) -> str:
    return f"MR-{nr}"


# ── Product data ─────────────────────────────────────────────────────
# (art_nr, name, subcategory, dn, length_mm, price, unit, angle, dn_abgang)

PRODUCTS: list[tuple] = []


# ── KGEM-Rohre ──

def _add_kgem(length_mm: int, data: dict[int, tuple[str, float]], price_is_per_meter: bool = False):
    for dn, (art, price) in data.items():
        length_m = length_mm / 1000
        if price_is_per_meter:
            total = round(price * length_m, 2)
        else:
            total = price
        name = f"KGEM Kanalrohr DN{dn} SN4 L={length_m}m"
        PRODUCTS.append((art, name, "KG-Rohre", dn, length_mm, total, "Stk", None, None))

# 500mm (Preis/Stück)
_add_kgem(500, {
    110: ("202001", 47.60),
    125: ("202005", 96.80),
    160: ("202009", 154.05),
    200: ("202013", None),  # no price listed clearly — skip
})
# Fix: 200mm 500mm has price 154.05? Let me re-check. The PDF shows DN200 500mm = 202013, 154,05
# Actually from PDF page 2: 500mm row: DN110=202001/47,60  DN125=202005/58,90  DN160=202009/96,80  DN200=202013/154,05
# Let me redo this properly.

PRODUCTS.clear()

# 500mm
_add_kgem(500, {
    110: ("202001", 47.60),
    125: ("202005", 58.90),
    160: ("202009", 96.80),
    200: ("202013", 154.05),
})

# 1000mm (Preis/Meter)
_add_kgem(1000, {
    110: ("202002", 60.85),
    125: ("202006", 76.65),
    160: ("202010", 118.50),
    200: ("202014", 184.10),
    250: ("202017", 375.25),
    315: ("202020", 643.85),
    400: ("202023", 1137.60),
    500: ("202026", 2101.40),
})

# 2000mm (Preis/Meter)
_add_kgem(2000, {
    110: ("202003", 57.30),
    125: ("202007", 71.10),
    160: ("202011", 112.60),
    200: ("202015", 172.65),
    250: ("202018", 314.05),
    315: ("202021", 521.40),
    400: ("202024", 865.05),
    500: ("202027", 1532.60),
})

# 3000mm (Preis/Meter)
_add_kgem(3000, {
    110: ("1291508", 58.10),
    125: ("1304436", 72.30),
    160: ("1304437", 113.40),
    200: ("1304868", 175.40),
    250: ("1304869", 316.00),
    315: ("1304870", 501.65),
})

# 5000mm (Preis/Meter)
_add_kgem(5000, {
    110: ("202004", 57.15),
    125: ("202008", 68.95),
    160: ("202012", 109.05),
    200: ("202016", 165.55),
    250: ("202019", 297.05),
    315: ("202022", 489.80),
    400: ("202025", 782.10),
    500: ("202028", 1425.95),
})


# ── KGB-Bogen ──

_bogen = {
    (15, 110): ("202201", 38.95),
    (15, 125): ("202206", 77.40),
    (15, 160): ("202211", 92.05),
    (15, 200): ("202216", 193.50),
    (15, 250): ("202221", 496.25),
    (15, 315): ("202225", 778.30),
    (15, 400): ("202229", 2833.70),
    (15, 500): ("202233", 6854.20),

    (30, 110): ("202202", 40.25),
    (30, 125): ("202207", 77.85),
    (30, 160): ("202212", 94.60),
    (30, 200): ("202217", 194.15),
    (30, 250): ("202222", 662.20),
    (30, 315): ("202226", 963.20),
    (30, 400): ("202230", 3354.00),
    (30, 500): ("202234", 7417.50),

    (45, 110): ("202203", 40.00),
    (45, 125): ("202208", 81.70),
    (45, 160): ("202213", 91.85),
    (45, 200): ("202218", 207.30),
    (45, 250): ("202223", 739.60),
    (45, 315): ("202227", 1066.40),
    (45, 400): ("202231", 3452.90),
    (45, 500): ("202235", 9988.90),

    (67, 110): ("202204", 49.25),

    (87, 110): ("202205", 50.10),
    (87, 160): ("202215", 132.25),
    (87, 250): ("202224", 1272.80),
    (87, 315): ("202228", 1720.00),
    (87, 400): ("202232", 7172.40),
    (87, 500): ("202236", 19350.00),
}
for (angle, dn), (art, price) in _bogen.items():
    PRODUCTS.append((art, f"KGB Bogen {angle}° DN{dn}", "Formstücke", dn, None, price, "Stk", angle, None))


# ── KGAM-Aufklebemuffe ──

_aufklebemuffe = {
    110: ("203015", 55.50),
    125: ("203016", None),  # auf Anfrage
    160: ("203017", None),
    200: ("203018", None),
}
for dn, (art, price) in _aufklebemuffe.items():
    if price:
        PRODUCTS.append((art, f"KGAM Aufklebemuffe DN{dn}", "Formstücke", dn, None, price, "Stk", None, None))


# ── KGU-Überschiebmuffe ──

_ueberschiebmuffe = {
    110: ("203011", 40.85),
    125: ("203012", 65.80),
    160: ("203013", 97.65),
    200: ("203014", 162.55),
    250: ("203063", 447.20),
    315: ("203064", 920.20),
    400: ("203065", 1573.80),
    500: ("203066", 5955.50),
}
for dn, (art, price) in _ueberschiebmuffe.items():
    PRODUCTS.append((art, f"KGU Überschiebmuffe DN{dn}", "Formstücke", dn, None, price, "Stk", None, None))


# ── KGRE-Reinigungsrohr ──

_reinigung = {
    110: ("203023", 412.80),
    125: ("203024", 627.80),
    160: ("203025", 623.50),
    200: ("312132", 1311.50),
}
for dn, (art, price) in _reinigung.items():
    PRODUCTS.append((art, f"KGRE Reinigungsrohr DN{dn}", "Formstücke", dn, None, price, "Stk", None, None))


# ── KGEA-Einfachabzweig 45° ──

_abzweig45 = {
    (110, 110): ("202401", 91.60),
    (110, 125): ("202402", 145.35),
    (110, 160): ("202404", 151.40),
    (110, 200): ("202407", 284.05),
    (110, 250): ("202419", 1105.10),
    (110, 315): ("202422", 1698.50),
    (110, 400): ("202426", None),  # auf Anfrage
    (110, 500): ("1073992", None),

    (125, 125): ("202403", 159.55),
    (125, 160): ("202405", 186.85),
    (125, 200): ("202408", 417.10),
    (125, 250): ("202420", 1161.00),
    (125, 315): ("202423", None),
    (125, 400): ("202427", None),

    (160, 160): ("202406", 218.90),
    (160, 200): ("202409", 328.95),
    (160, 250): ("202411", 752.50),
    (160, 315): ("202413", 1212.60),
    (160, 400): ("202415", 4214.00),
    (160, 500): ("202417", 9855.60),

    (200, 200): ("202410", 419.25),
    (200, 250): ("202412", 834.20),
    (200, 315): ("202414", 3220.70),
    (200, 400): ("202416", 4854.70),
    (200, 500): ("202418", 13222.50),

    (250, 250): ("389783", 1483.50),
    (250, 315): ("202424", 3440.00),
    (250, 400): ("202428", 6746.70),
    (250, 500): ("202431", None),

    (315, 315): ("202425", 3603.40),
    (315, 400): ("202429", 14542.60),
    (315, 500): ("202432", 18545.90),

    (400, 400): ("202430", 18576.00),
    (400, 500): ("202433", None),

    (500, 500): ("202434", 33862.50),
}
for (dn_abg, dn_main), (art, price) in _abzweig45.items():
    if price:
        PRODUCTS.append((art, f"KGEA Einfachabzweig 45° DN{dn_main}/{dn_abg}",
                         "Formstücke", dn_main, None, price, "Stk", 45, dn_abg))


# ── KGEA-Einfachabzweig 87° ──

_abzweig87 = {
    (110, 110): ("202601", 86.45),
    (110, 125): ("202602", 197.80),
    (110, 160): ("202604", 168.60),
    (110, 200): ("202607", 533.20),
    (110, 250): ("202611", 1010.50),
    (110, 315): ("202616", 3392.70),
    (110, 400): ("202622", None),

    (125, 125): ("202603", 202.10),
    (125, 160): ("202605", 219.30),
    (125, 200): ("202608", None),
    (125, 250): ("202612", None),

    (160, 160): ("202606", 186.20),
    (160, 200): ("202609", 553.65),
    (160, 250): ("202613", 1199.70),
    (160, 315): ("202618", 3556.10),
    (160, 400): ("202624", 5310.50),
    (160, 500): ("202629", 12104.50),

    (200, 200): ("202610", 528.90),
    (200, 250): ("202614", 1586.70),
    (200, 315): ("202619", 4459.10),
    (200, 400): ("202625", None),

    (250, 250): ("202615", 1173.90),
    (250, 315): ("202620", None),
    (250, 400): ("202626", 7864.70),
    (250, 500): ("202631", None),

    (315, 315): ("202621", 4269.90),
    (315, 400): ("202627", None),
    (315, 500): ("202632", 18158.90),

    (400, 400): ("202628", 14439.40),
    (400, 500): ("202633", None),

    (500, 500): ("202634", 31106.20),
}
for (dn_abg, dn_main), (art, price) in _abzweig87.items():
    if price:
        PRODUCTS.append((art, f"KGEA Einfachabzweig 87° DN{dn_main}/{dn_abg}",
                         "Formstücke", dn_main, None, price, "Stk", 87, dn_abg))


# ── KGR-Übergangsrohr (Reduktion) ──

_reduktion = {
    (125, 110): ("203007", 52.90),
    (160, 110): ("203008", 69.70),
    (160, 125): ("203009", 91.20),
    (200, 160): ("203010", 147.95),
    (250, 200): ("203059", 614.90),
    (315, 250): ("203060", 1285.70),
    (400, 315): ("203061", 2236.00),
    (500, 400): ("203062", 7576.60),
}
for (dn_main, dn_abg), (art, price) in _reduktion.items():
    PRODUCTS.append((art, f"KGR Übergangsrohr DN{dn_main}/{dn_abg}",
                     "Formstücke", dn_main, None, price, "Stk", None, dn_abg))


# ── KGM-Muffenstopfen ──

_muffenstopfen = {
    110: ("203019", 19.80),
    125: ("203020", 28.40),
    160: ("203021", 39.15),
    200: ("203022", 79.15),
    250: ("203067", 434.30),
    315: ("203068", 765.40),
    400: ("203069", 1702.80),
    500: ("203070", 4016.20),
}
for dn, (art, price) in _muffenstopfen.items():
    PRODUCTS.append((art, f"KGM Muffenstopfen DN{dn}", "Formstücke", dn, None, price, "Stk", None, None))


# ── KGK-Kappen ──

_kappen = {
    110: ("203039", 34.65),
    125: ("203040", 54.20),
    160: ("203041", 76.15),
    200: ("234983", 98.50),
    250: ("203043", 511.70),
    315: ("203044", 924.50),
    400: ("203045", 1148.10),
    # 500: auf Anfrage
}
for dn, (art, price) in _kappen.items():
    PRODUCTS.append((art, f"KGK Kappe DN{dn}", "Formstücke", dn, None, price, "Stk", None, None))


# ── KG-USM Übergangsstück auf Steinzeugmuffe ──

_usm = {
    110: ("203035", 124.70),
    125: ("203036", 258.00),
    160: ("203037", 255.85),
    200: ("203038", 870.75),
    250: ("145544", 1952.20),
    315: ("145545", 2494.00),
}
for dn, (art, price) in _usm.items():
    PRODUCTS.append((art, f"KG-USM Übergangsstück auf Steinzeugmuffe DN{dn}",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── KGUS Übergangsstück auf STZ-Spitzende ──

_kgus = {
    110: ("203047", 156.95),
    125: ("203048", 389.15),
    160: ("203049", 350.45),
    200: ("203050", 1006.20),
}
for dn, (art, price) in _kgus.items():
    PRODUCTS.append((art, f"KGUS Übergangsstück auf STZ-Spitzende DN{dn}",
                     "Formstücke", dn, None, price, "Stk", None, None))


# ── KGUG Anschlussstück an Gussrohrspitzende ──

_kgug = {
    110: ("203027", 95.50),
    125: ("203028", None),  # auf Anfrage
    160: ("203029", 212.45),
    200: ("203030", None),
}
for dn, (art, price) in _kgug.items():
    if price:
        PRODUCTS.append((art, f"KGUG Anschlussstück an Gussrohrspitzende DN{dn}",
                         "Formstücke", dn, None, price, "Stk", None, None))


# ── Mengering-Doppeldichtung zu KGUG ──

_mengering = {
    110: ("203411", 57.20),
    125: ("203412", None),  # auf Anfrage
    160: ("389889", 115.70),
    200: ("203414", None),
}
for dn, (art, price) in _mengering.items():
    if price:
        PRODUCTS.append((art, f"Mengering-Doppeldichtung zu KGUG DN{dn}",
                         "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


# ── KP-Lippendichtring ──

_lippendichtring = {
    110: ("203407", 12.70),
    125: ("203408", 14.00),
    160: ("203409", 16.15),
    200: ("203410", 23.65),
    250: ("203415", 58.50),
    315: ("389897", 81.30),
    400: ("203417", 156.95),
    500: ("203418", 360.80),
}
for dn, (art, price) in _lippendichtring.items():
    PRODUCTS.append((art, f"KP Lippendichtring DN{dn}",
                     "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


# ── KGUS Profilring (Typ Wavin) ──

_profilring_wavin = {
    110: ("203423", 101.95),
    125: ("203424", 211.60),
    160: ("203425", 217.60),
    200: ("203426", 561.15),
}
for dn, (art, price) in _profilring_wavin.items():
    PRODUCTS.append((art, f"KGUS Profilring (Typ Wavin) DN{dn}",
                     "Dichtungen & Zubehör", dn, None, price, "Stk", None, None))


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
