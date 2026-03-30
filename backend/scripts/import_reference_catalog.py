from __future__ import annotations

import argparse
from dataclasses import dataclass

from sqlalchemy import delete, select

from app.database import SessionLocal
from app.models import Product


HERSTELLER = "Referenzkatalog Demo"
STATUS = "aktiv"
WAEHRUNG = "EUR"


@dataclass(frozen=True)
class ReferenceProductSpec:
    artikel_id: str
    artikelname: str
    artikelbeschreibung: str
    kategorie: str
    unterkategorie: str
    werkstoff: str | None = None
    nennweite_dn: int | None = None
    nennweite_od: int | None = None
    laenge_mm: int | None = None
    breite_mm: int | None = None
    hoehe_mm: int | None = None
    belastungsklasse: str | None = None
    steifigkeitsklasse_sn: str | None = None
    norm_primaer: str | None = None
    system_familie: str | None = None
    verbindungstyp: str | None = None
    dichtungstyp: str | None = None
    kompatible_dn_anschluss: str | None = None
    kompatible_systeme: str | None = None
    einsatzbereich: str | None = None
    einbauort: str | None = None
    ek_netto: float | None = None
    vk_listenpreis_netto: float | None = None
    preiseinheit: str = "Stk"
    lager_gesamt: int | None = 1
    lieferzeit_tage: int | None = 5


REFERENCE_PRODUCTS: list[ReferenceProductSpec] = [
    ReferenceProductSpec(
        artikel_id="REF-DRAINAGEROHR-DN100",
        artikelname="Drainagerohr DN100 gelocht",
        artikelbeschreibung="Referenzartikel fuer Drainagerohr DN100 zur LV-Zuordnung in der Demo.",
        kategorie="Kanalrohre",
        unterkategorie="Drainagerohr",
        nennweite_dn=100,
        laenge_mm=5000,
        ek_netto=8.5,
        vk_listenpreis_netto=12.5,
        preiseinheit="m",
        einsatzbereich="Drainage",
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-ABLAUFAUFSATZ-450-300X500-D400",
        artikelname="Beton Ablaufaufsatz 300/500 DN450 D400",
        artikelbeschreibung="Referenzartikel fuer Ablaufkombination aus Betonteilen mit Aufsatz 300/500 und Lastklasse D400.",
        kategorie="Straßenentwässerung",
        unterkategorie="Straßenablauf",
        werkstoff="Beton",
        nennweite_dn=450,
        breite_mm=300,
        laenge_mm=500,
        belastungsklasse="D400",
        ek_netto=165.0,
        vk_listenpreis_netto=238.0,
        einsatzbereich="Fahrbahn",
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTRING-DN450",
        artikelname="Beton Schachtring DN450",
        artikelbeschreibung="Referenzartikel fuer Schachtring DN450 in Ablaufkombinationen.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtring",
        werkstoff="Beton",
        nennweite_dn=450,
        ek_netto=42.0,
        vk_listenpreis_netto=61.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHAFTKONUS-DN450",
        artikelname="Beton Schaftkonus DN450",
        artikelbeschreibung="Referenzartikel fuer Schaftkonus DN450 in Straßenablaeufen.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachthals/Konus",
        werkstoff="Beton",
        nennweite_dn=450,
        ek_netto=58.0,
        vk_listenpreis_netto=84.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-ABLAUFBODEN-DN450-DN150-D400",
        artikelname="Beton Ablaufboden DN450 Anschluss DN150 D400",
        artikelbeschreibung="Referenzartikel fuer Ablaufboden mit Anschluss DN150 und Lastklasse D400.",
        kategorie="Straßenentwässerung",
        unterkategorie="Straßenablauf",
        werkstoff="Beton",
        nennweite_dn=450,
        belastungsklasse="D400",
        kompatible_dn_anschluss="150",
        ek_netto=118.0,
        vk_listenpreis_netto=171.0,
        einsatzbereich="Fahrbahn",
    ),
    ReferenceProductSpec(
        artikel_id="REF-STAHL-SCHMUTZFANGEIMER-DN450",
        artikelname="Verzinkter Schmutzfangeimer fuer Straßenablauf DN450",
        artikelbeschreibung="Referenzartikel fuer verzinkten Eimer/Schmutzfangeimer in Ablaufkombinationen.",
        kategorie="Straßenentwässerung",
        unterkategorie="Schmutzfangeimer",
        werkstoff="Stahl",
        nennweite_dn=450,
        ek_netto=24.0,
        vk_listenpreis_netto=36.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTUNTERTEIL-DN1000-DN250",
        artikelname="Beton Schachtunterteil DN1000 Anschluss DN250",
        artikelbeschreibung="Referenzartikel fuer Revisionsschacht-Unterteil DN1000 mit Anschluss bis DN250.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtunterteil",
        werkstoff="Beton",
        nennweite_dn=1000,
        kompatible_dn_anschluss="250",
        ek_netto=398.0,
        vk_listenpreis_netto=566.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTUNTERTEIL-DN800-DN200",
        artikelname="Beton Schachtunterteil DN800 Anschluss DN200",
        artikelbeschreibung="Referenzartikel fuer Revisionsschacht-Unterteil DN800 mit PP-/Beton-Anschluss DN160 bis DN400.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtunterteil",
        werkstoff="Beton",
        nennweite_dn=800,
        kompatible_dn_anschluss="160,200,300,400",
        ek_netto=342.0,
        vk_listenpreis_netto=488.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTRING-DN1000-H500-STEIGEISEN",
        artikelname="Beton Schachtring DN1000 H500 mit Steigeisen",
        artikelbeschreibung="Referenzartikel fuer Schachtring DN1000 H500 mit Steigeisen.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtring",
        werkstoff="Beton",
        nennweite_dn=1000,
        hoehe_mm=500,
        ek_netto=132.0,
        vk_listenpreis_netto=189.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTRING-DN1000-H500",
        artikelname="Beton Schachtring DN1000 H500 ohne Steigeisen",
        artikelbeschreibung="Referenzartikel fuer Schachtring DN1000 H500 ohne Steigeisen.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtring",
        werkstoff="Beton",
        nennweite_dn=1000,
        hoehe_mm=500,
        ek_netto=118.0,
        vk_listenpreis_netto=171.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTRING-DN800-H500",
        artikelname="Beton Schachtring DN800 H500",
        artikelbeschreibung="Referenzartikel fuer Schachtring DN800 H500.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtring",
        werkstoff="Beton",
        nennweite_dn=800,
        hoehe_mm=500,
        ek_netto=108.0,
        vk_listenpreis_netto=155.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-KONUS-DN1000-625",
        artikelname="Beton Konus DN1000/625",
        artikelbeschreibung="Referenzartikel fuer Schachtkonus DN1000/625.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachthals/Konus",
        werkstoff="Beton",
        nennweite_dn=1000,
        kompatible_dn_anschluss="625",
        ek_netto=176.0,
        vk_listenpreis_netto=252.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-KONUS-DN800-625",
        artikelname="Beton Konus DN800/625",
        artikelbeschreibung="Referenzartikel fuer Schachtkonus DN800/625.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachthals/Konus",
        werkstoff="Beton",
        nennweite_dn=800,
        kompatible_dn_anschluss="625",
        ek_netto=154.0,
        vk_listenpreis_netto=221.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-SCHACHTABDECKUNG-LW625-D400",
        artikelname="Schachtabdeckung LW625 D400 rund",
        artikelbeschreibung="Referenzartikel fuer runde Schachtabdeckung mit lichter Weite 625 mm und Lastklasse D400.",
        kategorie="Schachtabdeckungen",
        unterkategorie="Abdeckung",
        werkstoff="Gusseisen",
        nennweite_dn=625,
        belastungsklasse="D400",
        ek_netto=224.0,
        vk_listenpreis_netto=318.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-AUSGLEICHSRING-DN650-H100",
        artikelname="Beton Ausgleichsring DN650 H100",
        artikelbeschreibung="Referenzartikel fuer Ausgleichsring DN650 mit 10 cm Hoehe.",
        kategorie="Schachtbauteile",
        unterkategorie="Ausgleichsring",
        werkstoff="Beton",
        nennweite_dn=650,
        hoehe_mm=100,
        ek_netto=34.0,
        vk_listenpreis_netto=49.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-AUSGLEICHSRING-DN650-H60",
        artikelname="Beton Ausgleichsring DN650 H60",
        artikelbeschreibung="Referenzartikel fuer Ausgleichsring DN650 mit 6 cm Hoehe.",
        kategorie="Schachtbauteile",
        unterkategorie="Ausgleichsring",
        werkstoff="Beton",
        nennweite_dn=650,
        hoehe_mm=60,
        ek_netto=28.0,
        vk_listenpreis_netto=41.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-ACO-POWERDRAIN-V75-ANSCHLUSSKASTEN-DN100-D400",
        artikelname="Anschlusskasten ACO Powerdrain V75/100 DN100 D400",
        artikelbeschreibung="Referenzartikel fuer Anschlusskasten mit Anschluss DN100 passend zu ACO Powerdrain V75/100.",
        kategorie="Rinnen",
        unterkategorie="Anschlusskasten",
        nennweite_dn=100,
        belastungsklasse="D400",
        system_familie="Aco Powerdrain",
        kompatible_dn_anschluss="100",
        ek_netto=214.0,
        vk_listenpreis_netto=306.0,
        einsatzbereich="Oberflächenentwässerung",
    ),
    ReferenceProductSpec(
        artikel_id="REF-ACO-POWERDRAIN-V75-LAUB-SCHMUTZEIMER",
        artikelname="Laub- und Schmutzeimer fuer ACO Powerdrain V75/100",
        artikelbeschreibung="Referenzartikel fuer Laub- und Schmutzeimer passend zu ACO Powerdrain Anschlusskaesten.",
        kategorie="Rinnen",
        unterkategorie="Schmutzfangeimer",
        werkstoff="Stahl",
        system_familie="Aco Powerdrain",
        ek_netto=26.0,
        vk_listenpreis_netto=38.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-ACO-POWERDRAIN-EINLAUFKASTEN-DN100-D400",
        artikelname="Einlaufkasten ACO Powerdrain DN100 D400",
        artikelbeschreibung="Referenzartikel fuer Einlaufkasten passend zu ACO Powerdrain V100, DN100 und Lastklasse D400.",
        kategorie="Straßenentwässerung",
        unterkategorie="Einlaufkasten",
        nennweite_dn=100,
        belastungsklasse="D400",
        system_familie="Aco Powerdrain",
        kompatible_dn_anschluss="100,110",
        ek_netto=228.0,
        vk_listenpreis_netto=326.0,
        einsatzbereich="Oberflächenentwässerung",
    ),
    ReferenceProductSpec(
        artikel_id="REF-ACO-POWERDRAIN-ROST-100-D400",
        artikelname="Rost ACO Powerdrain V100 D400",
        artikelbeschreibung="Referenzartikel fuer Rost passend zu ACO Powerdrain V100 in Lastklasse D400.",
        kategorie="Rinnen",
        unterkategorie="Rost",
        nennweite_dn=100,
        belastungsklasse="D400",
        system_familie="Aco Powerdrain",
        ek_netto=88.0,
        vk_listenpreis_netto=126.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-ACO-POWERDRAIN-V75-ABSCHLUSSDECKEL",
        artikelname="Abschlussdeckel fuer ACO Powerdrain V75/100",
        artikelbeschreibung="Referenzartikel fuer Abschlussdeckel passend zu ACO Powerdrain V75/100.",
        kategorie="Rinnen",
        unterkategorie="Stirnwand",
        system_familie="Aco Powerdrain",
        ek_netto=19.0,
        vk_listenpreis_netto=29.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-STRASSENABLAUF-DN160-D400",
        artikelname="Straßenablauf aus Beton DN160 D400",
        artikelbeschreibung="Referenzartikel fuer Straßenablauf aus Betonfertigteilen nach DIN 4052 mit Anschluss DN160.",
        kategorie="Straßenentwässerung",
        unterkategorie="Straßenablauf",
        werkstoff="Beton",
        nennweite_dn=160,
        belastungsklasse="D400",
        norm_primaer="DIN 4052",
        kompatible_dn_anschluss="160",
        ek_netto=212.0,
        vk_listenpreis_netto=304.0,
        einsatzbereich="Fahrbahn",
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-STRASSENABLAUF-AUFSATZ-500X300-D400",
        artikelname="Aufsatz fuer Straßenablauf Pultform 500/300 D400",
        artikelbeschreibung="Referenzartikel fuer Straßenablauf-Aufsatz in Pultform 500/300 mm, Lastklasse D400.",
        kategorie="Straßenentwässerung",
        unterkategorie="Straßenablauf",
        werkstoff="Beton",
        nennweite_dn=100,
        laenge_mm=500,
        breite_mm=300,
        belastungsklasse="D400",
        norm_primaer="DIN 4052",
        ek_netto=138.0,
        vk_listenpreis_netto=198.0,
        einsatzbereich="Fahrbahn",
    ),
    ReferenceProductSpec(
        artikel_id="REF-HAURATON-FASERFIX-SINKKASTEN-100-DN100-D400",
        artikelname="Sinkkasten FASERFIX 100 DN100 D400",
        artikelbeschreibung="Referenzartikel fuer Sinkkasten/Geruchsverschluss passend zu FASERFIX 100 mit Anschluss DN100 und Lastklasse D400.",
        kategorie="Rinnen",
        unterkategorie="Sinkkasten",
        werkstoff="Beton",
        nennweite_dn=100,
        belastungsklasse="D400",
        system_familie="Faserfix",
        kompatible_dn_anschluss="100",
        ek_netto=196.0,
        vk_listenpreis_netto=281.0,
        einsatzbereich="Oberflächenentwässerung",
    ),
    ReferenceProductSpec(
        artikel_id="REF-HAURATON-FASERFIX-SCHMUTZFANGEIMER-100",
        artikelname="Schmutzfangeimer FASERFIX 100 verzinkt",
        artikelbeschreibung="Referenzartikel fuer Schmutzfangeimer passend zu FASERFIX 100.",
        kategorie="Rinnen",
        unterkategorie="Schmutzfangeimer",
        werkstoff="Stahl",
        system_familie="Faserfix",
        ek_netto=22.0,
        vk_listenpreis_netto=33.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-HAURATON-FASERFIX-ROST-100-D400",
        artikelname="Stegguss-Rost FASERFIX 100 D400",
        artikelbeschreibung="Referenzartikel fuer Rostbreite 100 mm und Lastklasse D400 passend zu FASERFIX.",
        kategorie="Rinnen",
        unterkategorie="Rost",
        nennweite_dn=100,
        belastungsklasse="D400",
        system_familie="Faserfix",
        breite_mm=100,
        ek_netto=74.0,
        vk_listenpreis_netto=106.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-HAURATON-FASERFIX-STIRNWAND-100",
        artikelname="End- und Anfangsdeckel FASERFIX 100",
        artikelbeschreibung="Referenzartikel fuer Stirnwand/Enddeckel passend zu FASERFIX 100.",
        kategorie="Rinnen",
        unterkategorie="Stirnwand",
        nennweite_dn=100,
        system_familie="Faserfix",
        ek_netto=18.0,
        vk_listenpreis_netto=27.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-KABELSCHACHT-700X700-D400",
        artikelname="Kabelschacht 700x700 aus Fertigteilen D400",
        artikelbeschreibung="Referenzartikel fuer Kabelschacht 70/70 cm mit Deckel, Zwischenrahmen, Kastenrahmen und Bodenplatte.",
        kategorie="Kabelschutz",
        unterkategorie="Kabelschacht",
        werkstoff="Beton",
        breite_mm=700,
        laenge_mm=700,
        belastungsklasse="D400",
        ek_netto=468.0,
        vk_listenpreis_netto=669.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-BETON-LATERNENHUELSE-DN300",
        artikelname="Laternenhuelse DN300",
        artikelbeschreibung="Referenzartikel fuer Laternenhuelse aus Beton oder PVC-Rohr DN300.",
        kategorie="Kabelschutz",
        unterkategorie="Laternenhülse",
        werkstoff="Beton",
        nennweite_dn=300,
        ek_netto=64.0,
        vk_listenpreis_netto=92.0,
    ),
    ReferenceProductSpec(
        artikel_id="REF-KABUFLEX-R-PLUS-450-DN110",
        artikelname="Kabuflex R plus 450 DN110",
        artikelbeschreibung="Referenzartikel fuer Kabel-Leerrohr DN110, System Kabuflex R plus 450.",
        kategorie="Kabelschutz",
        unterkategorie="Leerrohr",
        werkstoff="PE",
        nennweite_dn=110,
        nennweite_od=110,
        laenge_mm=6000,
        system_familie="Kabuflex",
        steifigkeitsklasse_sn="SN 8",
        ek_netto=6.8,
        vk_listenpreis_netto=9.9,
        preiseinheit="m",
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-KABUFLEX-MUFFE-DN110",
        artikelname="Kabuflex Muffe DN110",
        artikelbeschreibung="Referenzartikel fuer Verbindungsmuffe DN110 im System Kabuflex.",
        kategorie="Kabelschutz",
        unterkategorie="Muffe",
        werkstoff="PE",
        nennweite_dn=110,
        system_familie="Kabuflex",
        ek_netto=8.0,
        vk_listenpreis_netto=11.5,
    ),
    ReferenceProductSpec(
        artikel_id="REF-WAVIN-XS-400-SCHACHTUNTERTEIL-DN400-DN100",
        artikelname="Wavin XS 400 Schachtunterteil DN400 Anschluss DN100",
        artikelbeschreibung="Referenzartikel fuer Wavin XS 400 Schachtunterteil DN400 mit Anschluss DN100.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtunterteil",
        werkstoff="PP",
        nennweite_dn=400,
        system_familie="Wavin XS",
        verbindungstyp="Steckmuffe",
        dichtungstyp="Lippendichtung",
        kompatible_dn_anschluss="100",
        ek_netto=246.0,
        vk_listenpreis_netto=352.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-WAVIN-XS-400-SCHACHTUNTERTEIL-DN400-DN150",
        artikelname="Wavin XS 400 Schachtunterteil DN400 Anschluss DN150",
        artikelbeschreibung="Referenzartikel fuer Wavin XS 400 Schachtunterteil DN400 mit Anschluss DN150.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtunterteil",
        werkstoff="PP",
        nennweite_dn=400,
        system_familie="Wavin XS",
        verbindungstyp="Steckmuffe",
        dichtungstyp="Lippendichtung",
        kompatible_dn_anschluss="150",
        ek_netto=254.0,
        vk_listenpreis_netto=363.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-WAVIN-XS-400-SCHACHTROHR-DN400",
        artikelname="Wavin XS 400 Schachtrohr DN400",
        artikelbeschreibung="Referenzartikel fuer Wavin XS 400 Schachtrohr DN400.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtrohr",
        werkstoff="PP",
        nennweite_dn=400,
        system_familie="Wavin XS",
        ek_netto=92.0,
        vk_listenpreis_netto=131.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-AWASCHACHT-DN800-SCHACHTUNTERTEIL-DN160",
        artikelname="AWASCHACHT DN800 Schachtunterteil DN160",
        artikelbeschreibung="Referenzartikel fuer PP-Kunststoffschacht DN800 mit Anschluss DN160 im System AWASCHACHT.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtunterteil",
        werkstoff="PP",
        nennweite_dn=800,
        system_familie="AWASCHACHT",
        verbindungstyp="Steckmuffe",
        dichtungstyp="Lippendichtung",
        kompatible_dn_anschluss="110,160,200",
        ek_netto=418.0,
        vk_listenpreis_netto=596.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-AWASCHACHT-DN800-SCHACHTROHR",
        artikelname="AWASCHACHT DN800 Schachtrohr",
        artikelbeschreibung="Referenzartikel fuer PP-Schachtrohr DN800 im System AWASCHACHT.",
        kategorie="Schachtbauteile",
        unterkategorie="Schachtrohr",
        werkstoff="PP",
        nennweite_dn=800,
        system_familie="AWASCHACHT",
        ek_netto=164.0,
        vk_listenpreis_netto=234.0,
        einsatzbereich="Erdeinbau",
    ),
    ReferenceProductSpec(
        artikel_id="REF-AWASCHACHT-ABDECKUNG-LW625-D400",
        artikelname="AWASCHACHT Abdeckung LW625 D400",
        artikelbeschreibung="Referenzartikel fuer AWASCHACHT Schachtabdeckung mit lichter Weite 625 mm und Lastklasse D400.",
        kategorie="Schachtabdeckungen",
        unterkategorie="Abdeckung",
        werkstoff="Gusseisen",
        nennweite_dn=625,
        belastungsklasse="D400",
        system_familie="AWASCHACHT",
        ek_netto=238.0,
        vk_listenpreis_netto=339.0,
    ),
]


def _build_product(spec: ReferenceProductSpec) -> Product:
    return Product(
        artikel_id=spec.artikel_id,
        hersteller=HERSTELLER,
        hersteller_artikelnr=spec.artikel_id.removeprefix("REF-"),
        artikelname=spec.artikelname,
        artikelbeschreibung=spec.artikelbeschreibung,
        kategorie=spec.kategorie,
        unterkategorie=spec.unterkategorie,
        werkstoff=spec.werkstoff,
        nennweite_dn=spec.nennweite_dn,
        nennweite_od=spec.nennweite_od,
        laenge_mm=spec.laenge_mm,
        breite_mm=spec.breite_mm,
        hoehe_mm=spec.hoehe_mm,
        belastungsklasse=spec.belastungsklasse,
        steifigkeitsklasse_sn=spec.steifigkeitsklasse_sn,
        norm_primaer=spec.norm_primaer,
        system_familie=spec.system_familie,
        verbindungstyp=spec.verbindungstyp,
        dichtungstyp=spec.dichtungstyp,
        kompatible_dn_anschluss=spec.kompatible_dn_anschluss,
        kompatible_systeme=spec.kompatible_systeme or spec.system_familie,
        einsatzbereich=spec.einsatzbereich,
        einbauort=spec.einbauort,
        ek_netto=spec.ek_netto,
        vk_listenpreis_netto=spec.vk_listenpreis_netto,
        waehrung=WAEHRUNG,
        preiseinheit=spec.preiseinheit,
        lager_gesamt=spec.lager_gesamt,
        lieferant_1_lieferzeit_tage=spec.lieferzeit_tage,
        status=STATUS,
    )


def run_import(replace_existing: bool) -> None:
    db = SessionLocal()
    try:
        if replace_existing:
            deleted = db.execute(delete(Product).where(Product.artikel_id.like("REF-%"))).rowcount or 0
            print(f"Deleted existing reference products: {deleted}")

        existing = set(db.scalars(select(Product.artikel_id).where(Product.artikel_id.like("REF-%"))).all())
        added = 0
        updated = 0

        for spec in REFERENCE_PRODUCTS:
            product = _build_product(spec)
            if product.artikel_id in existing:
                db.execute(
                    delete(Product).where(Product.artikel_id == product.artikel_id)
                )
                updated += 1
            else:
                added += 1
            db.add(product)
            existing.add(product.artikel_id)

        db.commit()
        print(f"Reference catalog import complete: {added} added, {updated} refreshed")
        print(f"Total reference products in DB: {len(existing)}")
    finally:
        db.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import curated reference products for the demo catalog")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete all existing REF-* rows before importing the current reference catalog.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_import(replace_existing=args.replace)


if __name__ == "__main__":
    main()
