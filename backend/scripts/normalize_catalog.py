#!/usr/bin/env python3
"""Einmalige Normalisierung der Produktkatalog-Daten.

Fixes:
- Kategorie-Schreibweisen vereinheitlichen (Umlaute)
- Belastungsklassen-Formate (Leerzeichen, Tippfehler)
- Material-Schreibweisen normalisieren
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "tiefbaux.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    print("=== Kategorie-Normalisierung ===")
    category_fixes = [
        ("Strassenentwässerung", "Straßenentwässerung"),
        ("Formstuecke", "Formstücke"),
        ("Dichtungen & Zubehoer", "Dichtungen & Zubehör"),
    ]
    for old, new in category_fixes:
        cur.execute("UPDATE products SET kategorie = ? WHERE kategorie = ?", (new, old))
        print(f"  {old} → {new}: {cur.rowcount} Zeilen")

    print("\n=== Belastungsklassen-Normalisierung ===")
    load_fixes = [
        ("B 125", "B125"),
        ("D 400", "D400"),
        ("C251", "C250"),  # Tippfehler
    ]
    for old, new in load_fixes:
        cur.execute("UPDATE products SET belastungsklasse = ? WHERE belastungsklasse = ?", (new, old))
        print(f"  {old} → {new}: {cur.rowcount} Zeilen")

    # D110 ist kein Belastungsklassen-Wert sondern ein DN — auf NULL setzen
    cur.execute("UPDATE products SET belastungsklasse = NULL WHERE belastungsklasse = 'D110'")
    print(f"  D110 → NULL (kein Belastungswert): {cur.rowcount} Zeilen")

    print("\n=== Material-Normalisierung ===")
    material_fixes = [
        ("PE 100-RC", "PE 100 RC"),
        ("PVC", "PVC-U"),
        ("Guss", "Gusseisen"),
        ("PE-HD", "PE"),
    ]
    for old, new in material_fixes:
        cur.execute("UPDATE products SET werkstoff = ? WHERE werkstoff = ?", (new, old))
        print(f"  {old} → {new}: {cur.rowcount} Zeilen")

    conn.commit()
    conn.close()
    print("\nFertig.")


if __name__ == "__main__":
    main()
