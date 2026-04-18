"""LLM-first LV parsing: Gemini extracts positions, quantities, classification and parameters in one pass."""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from typing import Any

import httpx
import pdfplumber
from pypdf import PdfReader

from ..config import settings
from ..schemas import LVPosition, ProjectMetadata, TechnicalParameters
from .ai_interpreter import InterpretationError, _infer_with_heuristics, _maybe_reclassify_as_material, _normalize_json_content, _post_merge_sanity

logger = logging.getLogger(__name__)


def _gemini_models() -> list[str]:
    models = [settings.gemini_model, *settings.gemini_fallback_models]
    deduped: list[str] = []
    for model in models:
        normalized = (model or "").strip()
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _should_retry_gemini(status_code: int | None, exc: Exception | None = None) -> bool:
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError))
    return status_code in {408, 425, 429, 500, 502, 503, 504}


def _post_gemini(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    last_error: Exception | None = None
    for model in _gemini_models():
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={settings.gemini_api_key}"
        )
        for attempt in range(settings.gemini_retry_attempts):
            try:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(endpoint, json=payload)
                if response.status_code >= 400:
                    message = f"Gemini API error ({model}): {response.status_code} {response.text}"
                    if attempt + 1 < settings.gemini_retry_attempts and _should_retry_gemini(response.status_code):
                        time.sleep(0.6 * (attempt + 1))
                        continue
                    last_error = InterpretationError(message)
                    break
                return response.json()
            except Exception as exc:
                if attempt + 1 < settings.gemini_retry_attempts and _should_retry_gemini(None, exc):
                    time.sleep(0.6 * (attempt + 1))
                    continue
                last_error = InterpretationError(f"Gemini request failed ({model}): {exc}")
                break
    if last_error is None:
        last_error = InterpretationError("Gemini request failed without response")
    raise last_error

SYSTEM_INSTRUCTION = (
    "Du bist ein erfahrener Tiefbau-Fachberater bei einem Baustoffhaendler. "
    "Du analysierst Leistungsverzeichnisse (LV) aus Bauausschreibungen.\n\n"
    "Deine Aufgabe:\n"
    "1. Finde ALLE bepreisbaren Positionen im Text. Eine Position hat eine Ordnungszahl "
    "(z.B. '1.5.3'), eine Beschreibung, eine Menge und eine Einheit.\n"
    "2. Klassifiziere jede Position als 'material' oder 'dienstleistung'.\n"
    "3. Extrahiere technische Parameter fuer Material-Positionen.\n\n"
    "Regeln fuer die Klassifikation:\n"
    "- 'material': Positionen die ein physisches Produkt erfordern das geliefert werden muss "
    "(Rohre, Schachtteile, Abdeckungen, Formstücke, Rinnen, Dichtungen, Geotextilien, Vlies, "
    "Kies, Sand zum Einbau etc.)\n"
    "- 'dienstleistung': Reine Arbeitsleistungen OHNE Materialbedarf aus dem Baustoffhandel: "
    "Abbruch, Demontage, Rueckbau, Erdarbeiten (Aushub, Grabenaushub, Grabentiefe, "
    "Verfuellung, Verdichtung, Planum, Boden loesen, Boden einbauen, Bodenabfuhr), "
    "Transport, Entsorgung, Baustelleneinrichtung, Vermessung, Verkehrssicherung, "
    "Wasserhaltung, Stundenlohnarbeiten, Vorhaltung, Sperrung, Druckprobe, Absicherung, "
    "Roden, Aufnehmen und Entsorgen von Bestandsmaterial (Pflaster, Asphalt, Bordsteine, "
    "Zaeune, Tore, Leuchten etc.), Ausbauen bestehender Leitungen/Schaechte, "
    "Oberflaeche wiederherstellen, Asphalt einbauen, Pflaster verlegen (ohne Materiallieferung)\n"
    "- WICHTIG: 'aufnehmen und entsorgen', 'ausbauen und entsorgen', 'abbrechen', 'demontieren', "
    "'rueckbauen', 'roden', 'entfernen' = IMMER 'dienstleistung', auch wenn technische Begriffe "
    "wie DN oder Schacht vorkommen!\n"
    "- Wenn eine Position Material UND Einbauarbeit beschreibt (z.B. 'KG-Rohr DN150 liefern und "
    "verlegen'), klassifiziere als 'material'.\n"
    "- KRITISCH: Eine Position ist auch dann 'material', wenn nur ein Verlege-/Setz-Verb genannt "
    "wird ('setzen', 'verlegen', 'versetzen', 'einbauen', 'herstellen'), sofern die Position ein "
    "KONKRETES Bauteil mit eigenem Werkstoff oder eigener Abmessung nennt. Beispiel: "
    "'Bordstein aus Beton HB 15x25 cm setzen' → MATERIAL (Bordstein wird geliefert und gesetzt, "
    "auch wenn 'liefern' fehlt). 'Muldenrinne aus Naturstein setzen' → MATERIAL. "
    "'Dränmatte anbringen' → MATERIAL. "
    "Der AN bringt in Tiefbau-LVs grundsaetzlich das genannte Bauteil mit, sofern nicht "
    "explizit 'beigestellt' oder 'vom AG geliefert' vermerkt ist.\n"
    "- KRITISCH: Wenn die Position einen KONKRET spezifizierten, liefer­baren Werkstoff mit "
    "Guete-/Festigkeits-/Moertelklasse nennt (z.B. 'Spritzmoertel MG III', 'Fugenmoertel MG III', "
    "'Beton C25/30 XF2', 'Fugenmoertel nach DIN EN 13888', 'Pflastermoertel PM 5'), dann ist "
    "die Position 'material' — auch wenn die Ueberschrift ein Taetigkeitsverb enthaelt "
    "('Mauerwerksfugen verfugen', 'Fuge herstellen', 'Mauerwerk ausbessern mit Spritzmoertel'). "
    "Begruendung: Moertel, Beton in Festigkeits-/Expositionsklasse und Fugenmaterial sind "
    "liefer­bare Produkte aus dem Baustoffhandel. Der Einbau ist Nebenleistung.\n"
    "- GRENZFALL 'schneiden/bearbeiten': Wenn die Kernleistung ein Schneide-/Bearbeitungsvorgang "
    "an bereits anderswo gelieferten Bauteilen ist (Verben: 'schneiden', 'kürzen', 'ausklinken', "
    "'zuschneiden', 'nachbearbeiten') UND die Position 'Bruchmaterial entsorgen' oder "
    "'Nebenarbeiten' nennt, ist es 'dienstleistung' — auch wenn 'inkl. Materiallieferungen' steht "
    "(damit sind meist Verschleiss-/Hilfsmaterialien gemeint, nicht neue Bauteile). "
    "NUR wenn die Position einen EIGENEN konkreten Werkstoff UND eigene Abmessungen des "
    "gelieferten Bauteils nennt (z.B. 'Bordsteine aus Beton 10/25/100 liefern und zuschneiden'), "
    "ist es 'material'.\n"
    "- WICHTIG: Beachte den Gewerk-Kontext anhand der Ordnungszahl-Praefix:\n"
    "  OZ 25.xxx = Gasversorgung → Rohre sind 'Gasrohre' (nicht Kanalrohre!)\n"
    "  OZ 30.xxx = Wasserversorgung → Rohre sind 'Wasserrohre' (nicht Kanalrohre!)\n"
    "  OZ 35.xxx = Kabelschutz → Rohre sind 'Kabelschutz' (nicht Kanalrohre!)\n"
    "  OZ 01.xxx oder ohne klaren Gewerk-Praefix = Kanalrohre/Entwaesserung\n"
    "- WICHTIG: Wenn das Material vom Auftraggeber gestellt/beigestellt wird "
    "(z.B. 'wird durch den AG ... gestellt', 'ab Lager des AG', 'beigestellt'), "
    "ist es 'dienstleistung' - der Auftragnehmer liefert kein Material!\n"
    "- Verbindungsleitungen in der Hausinstallation (inkl. Fittings/Befestigungen) "
    "sind 'material', da der Auftragnehmer Rohr und Fittings mitbringt - "
    "gilt fuer Gas UND Wasser gleichermassen.\n\n"
    "Erkenne alle gaengigen Einheiten: m, m2, m², m3, m³, Stk, Stck, St, Stueck, kg, to, t, "
    "h, Std, StD, lfm, lfdm, lfd.m, Psch, psch, Pausch, Wo, mWo, cbm, etc.\n\n"
    "Gib ein JSON-Array zurueck. Jedes Objekt hat diese Felder:\n"
    "- ordnungszahl: string (z.B. '1.5.3')\n"
    "- description: string (Beschreibung der Position mit allen technischen Details wie Norm, SN-Klasse, DN, Material, Belastungsklasse — max 320 Zeichen)\n"
    "- quantity: number | null\n"
    "- unit: string | null\n"
    "- position_type: 'material' | 'dienstleistung'\n"
    "- article_type: string | null (PFLICHT fuer material — KEIN null! "
    "Kurzer deutscher Artikelname in 1-3 Woertern, der die Produktart benennt "
    "(was *ist* das Bauteil als Substantiv). Beispiele: 'Bordstein', 'Kurvenstein', 'Hochbord-Ecke', "
    "'Schachtabdeckung', 'KG-Rohr', 'Rohrbogen', 'Abzweig', "
    "'Entwaesserungsrinne', 'Straßenablauf', 'Schachtring', 'Stuetzmauerstein', "
    "'Pflasterstein', 'Blockstufe', 'Poller', 'Geotextil', 'Dränmatte', 'Bitumenfugenband'. "
    "Unabhaengig von product_category — auch Nicht-Sortiment-Artikel bekommen einen Namen. "
    "STRIKTE REGEL fuer position_type='material': article_type MUSS das Produkt-Substantiv sein, "
    "NIE ein Taetigkeitsverb oder eine Verb-Phrase. "
    "FALSCH: 'Bordstein setzen', 'Rinne herstellen', 'Rohr verlegen'. "
    "RICHTIG: 'Bordstein', 'Rinne' / 'Entwaesserungsrinne' / 'Muldenrinne', 'KG-Rohr'. "
    "Ignoriere Verben wie 'liefern', 'setzen', 'verlegen', 'herstellen', 'einbauen' — sie sind "
    "Nebenleistungen, NICHT Teil des article_type. "
    "Nur fuer position_type='dienstleistung': kurzer Taetigkeitsname erlaubt, z.B. 'Bordstein schneiden', "
    "'Pflaster aufnehmen', 'Grabenaushub', 'Druckprobe'.)\n"
    "- product_category: string | null (nur fuer material; verwende AUSSCHLIESSLICH "
    "einen dieser Werte oder null: Kanalrohre, Schachtabdeckungen, Schachtbauteile, "
    "Formstuecke, Strassenentwässerung, Rinnen, Dichtungen & Zubehoer, Geotextilien, "
    "Gasrohre, Wasserrohre, Druckrohre, Kabelschutz. "
    "Wenn keine Kategorie passt (z.B. Sand, Asphalt, Pflaster, Pflasterrinne, Bordsteine, Oberboden, Bitumenfugenband), "
    "setze null! WICHTIG: 'Pflasterrinne' ist KEINE Entwässerungsrinne sondern verlegte Pflastersteine — Kategorie null!)\n"
    "- product_subcategory: string | null (feinere Einordnung ODER Bauform-Kennzeichnung. "
    "Auch fuer Nicht-Sortiment-Positionen nutzen, wenn die Norm/das LV eine Bauform definiert, "
    "z.B. 'Form H', 'Form H F', 'Bauart BV', 'Bauart Tiefbord', 'Bauart Muldenstein' bei "
    "Bordsteinen nach DIN 483; 'Form I', 'Form II' bei Rinnen nach DIN 19580. "
    "Nutze die exakt im LV genannte Bezeichnung.)\n"
    "- material: string | null (PP, PVC-U, Stahlbeton, Beton, Polymerbeton, Gusseisen, HDPE, PE, PE 100, "
    "PE 100-RC, Steinzeug, Kunststoff. "
    "ABSOLUT STRIKT LITERAL: Uebernimm NUR, was das LV woertlich als Werkstoff des Hauptartikels nennt. "
    "VERBOT jeder Ableitung/Inferenz: Steht im LV nur 'Kunststoff', ist material='Kunststoff' — "
    "es ist ZWINGEND VERBOTEN, daraus 'PP' oder 'PVC-U' oder 'PE' zu machen, "
    "auch wenn kompatible Systeme (KG, HT, PE-HD) erwaehnt sind. "
    "Kompatibilitaets-Hinweise wie 'Anschluss fuer PVC-KG' oder 'passend fuer PE-HD-Rohr' beschreiben "
    "NICHT den Werkstoff des Artikels selbst und duerfen material NICHT beeinflussen. "
    "Nur wenn das LV den konkreten Werkstoff explizit dem Hauptartikel zuschreibt "
    "(z.B. 'Rueckstauklappe aus PP', 'Koerper: PVC-U'), uebernimm den konkreten Werkstoff.)\n"
    "- nominal_diameter_dn: integer | null (Bei Schaechten: 'Lichter Schachtdurchmesser' verwenden, NICHT "
    "den Zulauf-/Ablauf-DN! DN1.000 = 1000. "
    "ABSOLUTES VERBOT einer DN-Zuweisung bei folgenden Artikeltypen (ZWINGEND null, ganz egal welche Zahlen "
    "im LV stehen): Mauerscheibe, Mauerscheiben-Ecke, Stuetzwand, Winkelstein, L-Stein, Bordstein, "
    "Pflasterstein, Blockstufe, Rinnenstein, Muldenrinne aus Naturstein, Absenkstein, Kurvenstein. "
    "Diese Artikel haben KEINE Nennweite. Dort beschreiben Zahlen wie '100/130/12', 'Bauteilbreite 1,00 m' "
    "etc. IMMER nur Abmessungen; sie gehoeren in 'dimensions', NICHT hier. "
    "Bei Rohrklappen/Armaturen/Formstuecken, die 'Anschluss 110 mm (DA 110)' nennen, ist DN 100 gemeint — "
    "der Aussendurchmesser DA 110 mm entspricht DN 100 bei PVC.)\n"
    "- secondary_nominal_diameter_dn: integer | null (NUR setzen, wenn eine zweite, ANDERS GROSSE "
    "Nennweite vorhanden ist — bei Reduktionen/Uebergangsstuecken wie DN 200/160 -> 160. "
    "ABSOLUTES VERBOT, denselben Wert wie nominal_diameter_dn zu setzen. Beide Werte sind IMMER "
    "unterschiedlich oder secondary bleibt null. "
    "Konkrete Falle: Absperrschieber, Rohrklappen, Rueckstauklappen, Formstuecke mit EINER Nennweite "
    "(z.B. 'DN 100, Anschluss 110 mm') → nur primaere DN 100, secondary ZWINGEND null. "
    "Auch wenn der Artikel einen Ein- und einen Ausgang hat, aber beide gleich gross sind: secondary=null.)\n"
    "- load_class: string | null (A15, B125, C250, D400, E600, F900)\n"
    "- norm: string | null (Produkt-Norm DES HAUPTARTIKELS, z.B. 'DIN EN 1401', 'DIN EN 13476', "
    "'DIN EN 1916', 'DIN EN 13564 Typ 0'. Auch Richtzeichnungen/technische Regelwerke wie 'RiZ Was 7', "
    "'ZTV Asphalt', 'MVAS' — solche Kennungen gehoeren NICHT in product_subcategory, sondern hier in norm. "
    "HOECHSTE PRIORITAET: Wenn das LV einen expliziten Passus wie 'Norm: X', 'nach X', "
    "'Produkt nach X', 'zertifiziert nach X' UNMITTELBAR zum Hauptartikel nennt, uebernimm GENAU DIESE X "
    "als norm — selbst wenn im gleichen Text weitere DIN-Nummern fuer Zubehoer-/Anschlusssysteme "
    "erwaehnt sind. "
    "ABSOLUTES VERBOT: Normen KOMPATIBLER SYSTEME (z.B. 'Anschluss fuer PVC-KG-Rohr nach DIN 19534', "
    "'PE-HD-Rohr nach DIN 19537' bei einer Rohrklappe) duerfen NICHT in norm landen — sie gehoeren in "
    "'compatible_systems'. "
    "KONKRETES GEGENBEISPIEL: 'Rueckstauklappe/Rohrklappe, Norm: DIN EN 13564 Typ 0, "
    "Anschluss fuer PVC-KG-Rohr nach DIN 19534' → norm='DIN EN 13564 Typ 0' (NICHT DIN 19534!), "
    "compatible_systems=['PVC-KG'].)\n"
    "- stiffness_class_sn: integer | null (Ringsteifigkeitsklasse, z.B. 4, 8, 16 bei SN4, SN8, SN16)\n"
    "- dimensions: string | null (Abmessungen wie '300/500 mm', '500x500 mm', '12/15 x 25 x 50 cm' — "
    "insbesondere bei Aufsaetzen, Rosten, Rahmen, Rinnen, Bordsteinen. "
    "WICHTIG: IMMER die Einheit mitgeben. Wenn das LV die Einheit nicht direkt am Wert nennt, "
    "schaue in die Kontextzeilen der Position nach Angaben wie 'Abmessungen B/H/L in cm', "
    "'Masse in mm', 'Groesse in cm' — diese Einheit gilt dann fuer alle folgenden Abmessungs-Werte "
    "und MUSS an den Wert angehaengt werden. Beispiel: Header 'Abmessungen B/H/L in cm' + Zeile "
    "'12/15 x 25 x 50' → dimensions='12/15 x 25 x 50 cm'. "
    "Wenn die Einheit nirgends auffindbar ist, setze sie NICHT, sondern gib den Wert ohne Einheit an. "
    "NICHT aufnehmen: reine DN-/Nennweiten-Angaben, die bereits in nominal_diameter_dn stehen "
    "(z.B. 'Innendurchmesser 100 mm' → DN=100 reicht, dimensions bleibt null). "
    "Nur dann dimensions setzen, wenn echte Abmessungen in mehreren Richtungen (BxH, BxHxL, LxB) "
    "oder eine Profil-/Querschnitts-Angabe vorliegt. "
    "Bei SCHACHTRINGEN mit Format 'DN X/Y mm' bezeichnet der zweite Wert die Ringhoehe: DN=X wird "
    "als nominal_diameter_dn gesetzt, und der Y-Wert (Hoehe) kommt als 'Hoehe Y mm' in dimensions "
    "(z.B. 'DN 1000/250 mm' → DN=1000, dimensions='Hoehe 250 mm'). "
    "Wenn das LV MEHRERE zulaessige Abmessungen listet, uebernimm die erste hier (mit Einheit) und schreibe "
    "ALLE Varianten (ebenfalls mit Einheit) in das Feld 'variants'.)\n"
    "- color: string | null (Farbton/Ausfuehrung wenn genannt: 'grau', 'anthrazit', 'rot', "
    "'schwarz', 'sand', 'weiss'. Auch wenn Farbe nur in einer Nebenzeile wie 'Ausfuehrung: grau' "
    "oder als Appendix '...,grau' steht — immer extrahieren.)\n"
    "- variants: string[] | null (KRITISCH fuer die Zuordnung — KEINE Variante weglassen! "
    "variants ist NUR fuer AUFGEZAEHLTE Einzelwerte/Einzel-Auspraegungen gedacht, "
    "NICHT fuer kontinuierliche Bereiche ('von X bis Y'). "
    "Wenn das LV mehrere zulaessige Auspraegungen einer Position einzeln aufzaehlt, liste JEDE "
    "Variante einzeln als kurzes Label auf. TRIGGER-Signale fuer variants: "
    "• Zeilen die mit 'Kurvenradien', 'Radien', 'Laengen', 'Abmessungen', 'Masse', 'Ausfuehrung' "
    "beginnen und danach eine LISTE diskreter Werte enthalten (getrennt durch Zeilenumbruch, Komma, "
    "Schraegstrich, oder Bindestriche, die eine Liste bilden wie 'r = 0,5 -1,0 -1,5 -2,0'); "
    "• Aufzaehlungen wie 'konvex/konkav', 'Innenecke/Aussenecke', 'gewaschen innen/aussen'; "
    "• Wertereihen wie 'r = 0,5 -1,0 -1,5 -2,0 -3,0 -4,0 -5,0 -6,0' → ['r=0,5 m','r=1,0 m',"
    "'r=1,5 m','r=2,0 m','r=3,0 m','r=4,0 m','r=5,0 m','r=6,0 m'] (einzeln); "
    "• mehrere Groessenangaben: '12/15 x 25 x 50 / 12/15 x 25 x 100' → "
    "['12/15 x 25 x 50','12/15 x 25 x 100']. "
    "NICHT als variants erfassen: kontinuierliche Bereiche wie 'Halbmesser 2,50-5,00 m', "
    "'Radius 12-20 m', 'DN 100-200', 'Laenge 1-3 m'. Solche 'von-bis'-Angaben beschreiben einen "
    "Einsatzbereich und gehoeren als einzelner Eintrag in 'features' (z.B. 'Halbmesser 2,5-5,0 m'). "
    "Unterscheidung: eine LISTE ist 'r=0,5, 1,0, 1,5, 2,0' (diskrete Werte) — ein BEREICH ist "
    "'r=0,5 bis 2,0' oder 'r=0,5-2,0 m' (Spanne zwischen min und max). "
    "Eine Position ohne mehrfache diskrete Auspraegungen laesst variants null.)\n"
    "- reference_product: string | null (KRITISCH fuer die Zuordnung! "
    "Zwei Verwendungen: "
    "(a) explizit genannter Handelsname/Modell als Richtprodukt, z.B. 'z.B. ACO DRAIN Multiline', "
    "'wie Wavin Tegra 600', 'Typ BEGU 500'; "
    "(b) 'passend zu'-Bezug zu einem ANDEREN Bauteil/einer ANDEREN Form, z.B. bei Kurvensteinen "
    "oder Ecken, die zu einer bestimmten Bordstein-Form passen muessen: "
    "'passend zu H 12/15/25', 'passend zu H 15/25 (BV)', 'passend zur Form Tiefbord 8/20/100'. "
    "Uebernimm die genaue Referenz aus dem LV inkl. der Form-/Typenkennzeichnung. "
    "EINSCHRAENKUNG: reference_product NUR setzen, wenn eine explizite Verweis-Formulierung "
    "vorhanden ist ('passend zu', 'formgleich mit', 'abgestimmt auf', 'wie', 'z.B.', 'Typ'). "
    "Wenn die Bauform-Kennung (z.B. 'HB 15x25', 'Form H') ohne solche Vorsilbe genannt wird, "
    "gehoert sie in product_subcategory, NICHT in reference_product. "
    "reference_product und product_subcategory duerfen NICHT denselben Wert haben. "
    "Wichtig: product_subcategory bei erkennbarer Bauform (HB, Form H, Bauart BV, Muldenrinne, "
    "Tiefbord, Hochbord) IMMER fuellen — auch ohne Verweis-Formulierung.)\n"
    "- installation_area: string | null (Fahrbahn, Gehweg, Erdeinbau)\n"
    "- system_family: string | null (Produkt-/Systemfamilie DES ARTIKELS SELBST: KG PVC-U, Wavin Tegra, "
    "AWADUKT HPP, Wavin X-Stream, KG 2000. "
    "ABSOLUTES VERBOT, eine Familie zu setzen, mit der der Artikel nur KOMPATIBEL ist. "
    "Eine Rueckstau-/Rohrklappe mit Anschluss fuer KG-Rohre hat ZWINGEND system_family=null — "
    "die Kompatibilitaet gehoert ausschliesslich in 'compatible_systems'. "
    "Nur setzen, wenn das LV woertlich sagt, dass der HAUPTARTIKEL SELBST Teil der Familie ist "
    "(z.B. 'Wavin Tegra 600 Schacht', 'KG 2000 Rohr'). Im Zweifel: null.)\n"
    "- connection_type: string | null (Steckmuffe, Spitzende, Flansch, Muffe, Doppelmuffe, Klemmverbindung)\n"
    "- seal_type: string | null (Lippendichtung, Gleitringdichtung, Profildichtung, Doppeldichtung)\n"
    "- compatible_systems: string[] | null (Systeme/Anschlusswelten die explizit genannt werden, z.B. ['KG','HT'] oder ['PVC-KG','PE-HD'])\n"
    "- features: string[] | null (KRITISCH fuer die Produktauswahl. Liste JEDEN zuordnungsrelevanten "
    "Qualifier aus dem Positions-Text als eigenen Bullet-Stichpunkt (2-6 Woerter). "
    "Dies sind Details, die den konkreten Artikel bestimmen, aber NICHT bereits in einem anderen strukturierten "
    "Feld stehen. "
    "ABGRENZUNG ZU additional_specs: features beschreibt FORM, BAUART, GEOMETRIE, OPTIK, LIEFERUMFANG und "
    "AUSFUEHRUNGSART (wie der Artikel aussieht/konfektioniert ist). additional_specs beschreibt chemische/"
    "mechanische Materialeigenschaften und Pruef-/Norm-Anforderungen. Wenn ein Qualifier eindeutig in "
    "additional_specs gehoert (sulfatbestaendig, diffusionsoffen, Frost-/Tausalzwiderstand, CDF-Test, "
    "Biegezug, E-Modul usw.), NICHT zusaetzlich in features listen — jeder Qualifier nur in einem Feld. "
    "Beispiele fuer features-Qualifier-TYPEN (nicht Inhalt!): "
    "- integrierte Zubehoerteile/Ausstattung (z.B. 'mit Schmutzfaenger', 'mit Luefter', 'inkl. Spannring'); "
    "- bauliche Merkmale (z.B. 'selbstnivellierender Rahmen', 'daempfende Einlage', 'Doppelmuffe', 'mit Haltegriff'); "
    "- Oberflaeche/Beschichtung (z.B. 'gewaschen', 'gestrahlt', 'beschichtet', 'verzinkt'); "
    "- Ausfuehrungsart (z.B. 'einwalzbar', 'hoehenverstellbar', 'tagwasserdicht', 'druckdicht'); "
    "- Zulassung/Pruefzeichen (z.B. 'DIBt-Zulassung', 'DVGW-gepruft') sofern nicht in norm; "
    "- Einbausituation (z.B. 'fuer befahrbare Flaechen', 'Kellerentwaesserung') sofern nicht in installation_area; "
    "- vorgegebene Geometrie/Bauart (z.B. 'rund', 'eckig', 'konisch', 'teleskopierbar'); "
    "- Lieferumfang/Lieferform die den Artikel selbst bestimmt — WICHTIG auch bei Bordsteinen, Rinnen, Kantensteinen: "
    "'Geraden und Kurven ab R = 10 m', 'als Bogenstein lieferbar', 'in Geraden und Rundungen', "
    "'gerade und gebogen', 'als Innen- und Aussenecke', 'fuer Innen- und Aussenbogen'. "
    "Solche Formulierungen beschreiben den Lieferumfang (welche Ausfuehrungsformen geliefert werden muessen) "
    "und sind KEIN Einbauhinweis, selbst wenn sie im Satz mit 'liefern' oder 'versetzen' stehen; "
    "- inklusiv-Leistungen des Artikels (z.B. 'inkl. Dichtung', 'inkl. Edelstahlschrauben'). "
    "NICHT aufnehmen: Werte, die bereits in material/norm/DN/load_class/color/dimensions/installation_area/"
    "connection_type/seal_type/system_family stehen; reine Einbau-/Montage-Taetigkeiten ohne Artikelbezug "
    "(z.B. 'verlegen', 'setzen', 'fluchtgerecht versetzen') — aber eine im selben Satz genannte "
    "Lieferform-/Geometrieangabe ('in Geraden und Kurven ab R = X') gehoert SEHR WOHL in features, "
    "nur das reine Verb der Taetigkeit wird verworfen; "
    "Fundament-/Bettungsdetails, die Nebenleistung sind "
    "(z.B. 'Betonfundament C25/30', 'Rueckenstuetze 15 cm') — ausser sie beschreiben den Artikel selbst. "
    "Auch NICHT aufnehmen: 'inkl. X' fuer Nebenmaterialien, die im LV explizit als SEPARAT abzurechnen "
    "ausgewiesen sind (z.B. 'Kies ist ueber Vorpositionen 02.02.11 abzurechnen' → dann KEIN "
    "'inkl. Kiesschuettung' in features aufnehmen, die Kiesschuettung ist nicht Teil des Artikels). "
    "Generelle Regel: Wenn der LV-Text einen Passus wie 'abzurechnen ueber ...', 'in gesonderter "
    "Position', 'separate Position', 'ueber Vorposition' enthaelt, gilt das zugehoerige Material nicht "
    "als Lieferumfang dieses Artikels. "
    "Jeder Bullet muss fuer einen Baustoffhaendler entscheidungsrelevant sein. "
    "Wenn es keine zusaetzlichen Qualifier gibt, setze null. Max. 10 Bullets.)\n"
    "- installation_notes: string | null (Einbau- und Verlegehinweise, die im LV zur Position "
    "genannt sind, aber NICHT den zu liefernden Artikel selbst beschreiben. Gehoert hierher: "
    "Fundament-Angaben (z.B. 'Betonfundament C25/30, 20 cm, DIN 1045'), "
    "Rueckenstuetze (z.B. 'Rueckenstuetze 15 cm'), Bettung/Verguss (z.B. 'Moertelbett MG III', "
    "'Pflasterbettung 4 cm'), Planum-/Tragschichtangaben, Fugen-/Abdichtungshinweise, "
    "Verlegeart (z.B. 'flucht- und hoehengerecht versetzen', 'im Reihenverband'). "
    "Fasse diese Hinweise als lesbaren Satz zusammen (max. 600 Zeichen — lieber vollstaendig "
    "als abgeschnitten), z.B. 'Betonfundament C25/30, 20 cm, DIN 1045, Rueckenstuetze 15 cm'. "
    "Null wenn im LV keine Einbauhinweise stehen.)\n"
    "- compressive_strength: string | null (Druckfestigkeits-Klasse des GELIEFERTEN "
    "HAUPTARTIKELS selbst — NIEMALS des Fundaments, der Bettung, des Fugen-/Bettungsmoertels "
    "oder des Vergusses. Format 1 — Beton-Festigkeitsklasse nach DIN EN 206: 'C25/30', "
    "'C30/37' (exakt wie im LV). Format 2 — Festigkeits-Kennzeichen bei Bordsteinen/Pflaster "
    "nach DIN 483 / DIN EN 1340: 'Klasse 3' oder MPa-Angabe '≥ 15 MPa'. Format 3 — Moertel-"
    "klasse nach DIN EN 998-2: 'MG II', 'MG III', 'M 10' (nur wenn der Hauptartikel selbst "
    "ein Moertel/Kleber ist). Wenn der Hauptartikel ein NATURSTEIN-Produkt ist (Granit, "
    "Basalt, Gneis etc.), kommen Druckfestigkeits-Werte im Bereich 10-80 MPa fast immer vom "
    "Fundament/Moertel, nicht vom Stein (Naturstein hat typ. 200-400 MPa) — in dem Fall null "
    "setzen. Wenn die Position MEHRERE Festigkeitsangaben fuer verschiedene Komponenten "
    "nennt, nimm HIER nur die des Hauptartikels; die Nebenmaterial-Festigkeit gehoert in "
    "installation_notes.)\n"
    "- exposition_class: string | null (Expositionsklasse nach DIN EN 206 / DIN 1045-2, "
    "z.B. 'XC4', 'XF2', 'XF4', 'XD3', 'XA1'. Bei mehreren Klassen durch '/' oder '+' oder ',' "
    "getrennt: 'XD1/XF2', 'XC2/XF2 + XD1/XF2', 'XC4 + XF2 + XD3'. "
    "SETZEN, wenn der Hauptartikel ein BETON-/STAHLBETON-Produkt ist (Beton, Stahlbeton, "
    "Betonfertigteil, Polymerbeton, Mauerscheibe aus Stahlbeton, Betonrohr, Schachtring etc.) "
    "und im LV fuer diesen Artikel eine Expositionsklasse genannt ist — auch wenn die Klasse "
    "in einem Nebensatz wie 'Expositionsklassen XD1/XF2 (luftseitig) und XC2/XF2 (erdseitig)' "
    "steht. Bei Beton-Artikeln mit unterschiedlichen Klassen je Seite alle mit '/' oder ', ' "
    "zusammenfassen. "
    "NICHT SETZEN, wenn der Hauptartikel KEIN Beton-/Stahlbetonprodukt ist (Naturstein/Basalt/"
    "Granit/Gneis, Kunststoff/PVC/PE/PP/GFK, Gusseisen, unbeschichteter Stahl). In diesen "
    "Faellen gehoert jede im LV genannte X-Klasse zwingend zu einem Fundament-/Bettungsbeton "
    "und landet in installation_notes. Beispiel Naturstein: 'Muldenrinne aus Basalt, inkl. "
    "Fundamentbeton XF2' → null. Beispiel Stahlbeton: 'Mauerscheibe aus Stahlbeton, "
    "Expositionsklassen XD1/XF2/XC2' → 'XD1/XF2/XC2'.)\n"
    "- additional_specs: string[] | null (Pruef-/guete­relevante technische Anforderungen "
    "AUSSCHLIESSLICH an den GELIEFERTEN HAUPTARTIKEL — nicht an Nebenmaterialien. "
    "DIESES FELD ist fuer CHEMISCHE/MECHANISCHE MATERIALEIGENSCHAFTEN und PRUEF-/NORM-ANFORDERUNGEN "
    "gedacht, NICHT fuer Form/Geometrie/Ausfuehrung (die gehoeren in features). "
    "Pflicht-Aufnahme (sofern im LV genannt und dem Hauptartikel zuzuordnen): Materialchemie wie "
    "'sulfatbestaendig', 'diffusionsoffen', 'alkaliresistent', 'chloridfrei'; Dauerhaftigkeits-/"
    "Pruefanforderungen wie 'Frost-Tausalz-Widerstand', 'CDF-Test', 'Frostwiderstand Klasse X'; "
    "mechanische Kennwerte wie 'Biegezug ≥ x MPa', 'Haftzug ≥ x MPa', 'E-Modul'; "
    "Oberflaechen-Kennwerte wie 'Abriebwiderstand Klasse X', 'Rutschhemmung R11'. "
    "KRITISCH: Wenn der LV-Text eine Kennwertliste einem Nebenmaterial zuschreibt "
    "(Fugenmoertel, Fundamentbeton, Bettungsmoertel, Verguss, Vermoertelung, Klebstoff, "
    "Dichtmasse, Tragschicht), gehoeren diese Werte NICHT hierher — weder als ganze Liste, "
    "noch einzeln 'entkontextualisiert'. Sie werden ggf. kurz in installation_notes "
    "zusammengefasst und sonst verworfen. "
    "Heuristik zur Zuordnung: Wird eine Kennwertliste durch eine Ueberschrift, einen Doppel"
    "punkt oder einen einleitenden Satz einem Nebenmaterial zugeordnet (z.B. 'Fugenmoertel "
    "mit folgenden Eigenschaften:'), gilt die ganze nachfolgende Liste als Nebenmaterial-"
    "Spec. Im Zweifel: weglassen — lieber weniger Specs als falsch zugeordnete. "
    "Jedes Spec als eigener kurzer Bullet (max. 80 Zeichen), Schreibweise so nah am LV wie "
    "moeglich. Beispiele fuer Spec-TYPEN (nicht Inhalt!): "
    "• Mechanische Kennwerte DES HAUPTARTIKELS: 'Biegezugfestigkeit ≥ 6,0 N/mm²', "
    "'Spaltzugfestigkeit ≥ 4,0 MPa'; "
    "• Frost-/Tausalz-Widerstand: 'Frost-Tausalz-Widerstand CDF ≤ 1000 g/m²', "
    "'Frostwiderstand Klasse 3'; "
    "• Oberflaechen-/Verschleisskennwerte: 'Abriebwiderstand Klasse 4', 'Rutschhemmung R11'; "
    "• Wasseraufnahme/Dichtheit: 'Wasseraufnahme ≤ 6 Gew.-%'; "
    "• Pruef-/Regelwerk-Verweise: 'TL Pflaster-StB', 'RiZ Was 7', 'ZTV Asphalt-StB'; "
    "• Geometrie-Anforderungen (nur wenn nicht in dimensions): 'Fugentiefe 3-6 cm', "
    "'Fasenbreite 2-4 mm'; "
    "• Zulassungen: 'bauaufsichtliche Zulassung', 'DIBt-Zulassung Nr. Z-xx.xx'. "
    "NICHT aufnehmen: (a) Werte, die in anderen strukturierten Feldern stehen (DN, norm, "
    "load_class, material, compressive_strength, exposition_class, color); "
    "(b) Kennwerte von Nebenmaterialien (siehe oben); "
    "(c) E-Modul / Festigkeiten im Moertel-/Beton-Bereich (E-Modul ~17-40 GPa, "
    "Druckfestigkeit 20-80 MPa, Haftzug/Biegezug 1-6 MPa), wenn der Hauptartikel KEIN "
    "Beton-/Moertelprodukt ist (z.B. Rinnen aus Hartgestein, Pflastersteine aus Naturstein, "
    "Rohre/Formstuecke) — solche Werte stammen fast immer vom Fugen-/Fundamentmaterial. "
    "KONKRETES GEGENBEISPIEL: Bei 'Muldenrinne aus Naturstein (Basalt), inkl. Fundamentbeton "
    "XF2 und Fugenmoertel Typ A' mit anschliessender Liste 'Druckfestigkeit 40-70 MPa, "
    "Biegezugfestigkeit 6 MPa, Haftzug 1,5 MPa, E-Modul 17-22 GPa, CDF ≤ 500 g/m²' gehoert "
    "KEIN EINZIGER dieser Werte in additional_specs — sie beschreiben alle den Fugenmoertel, "
    "nicht den Basaltstein. Die additional_specs bleiben in dem Fall leer (null). "
    "Max. 12 Bullets. Lieber kleinteilig pro Kennwert eine eigene Zeile als eine lange "
    "kombinierte Zeile, damit die Anzeige uebersichtlich bleibt.)\n"
    "- sortiment_relevant: boolean (true wenn ein Tiefbau-Baustoffhaendler dieses Produkt"
    "fuehren wuerde: Rohre, Schaechte, Formstücke, Abdeckungen, Rinnen, Dichtungen, "
    "Geotextilien, Druckrohre, Kabelschutzrohre. "
    "false fuer: Stuetzmauern, Bordsteine, Pflaster, Pflasterrinne, Asphalt, Poller, Blockstufen, "
    "Sand/Kies/Schotter als reines Schuettgut, Hydrantenarmaturen, Zaeune, Beleuchtung, "
    "Rasensaat, Oberboden, Hausanschlussgarnituren, Bitumenfugenband, Mauerscheiben, Trennlagen/Folien. "
    "Bei Dienstleistungen: false)\n\n"
    "Fuer Dienstleistungs-Positionen setze alle technischen Parameter auf null.\n"
    "Ueberspringe Ueberschriften (z.B. '1.5 Entwaesserungsleitungen'), Vorbemerkungen, "
    "Hinweise und nicht-bepreisbare Zeilen (ohne Menge/Einheit).\n\n"
    "WICHTIG - Seitenumbrueche: Positionen koennen ueber Seitenumbrueche gehen. "
    "Wenn eine Seite mit 'Leistungsbeschreibung auf voranstehender Seite' oder "
    "aehnlichem Fortsetzungstext beginnt, gefolgt von einer Menge und Einheit, "
    "gehoert diese Menge zur letzten Position der vorherigen Seite. "
    "Die Menge/Einheit am ENDE einer Position (direkt vor der naechsten Positionsnummer "
    "oder vor 'Uebertrag') ist IMMER die korrekte Gesamtmenge der Position - "
    "NICHT einzelne Stueckzahlen aus der Komponentenliste innerhalb der Beschreibung!\n"
    "Gib NUR das JSON-Array zurueck, keine Erklaerung."
)


COMBINED_SYSTEM_INSTRUCTION = (
    SYSTEM_INSTRUCTION
    + "\n\n"
    + "ZUSAETZLICH: Extrahiere die Projekt-Metadaten aus dem Deckblatt/Kopfbereich des LV.\n"
    "Metadata-Felder:\n"
    "- bauvorhaben: string | null (Bauvorhaben-Bezeichnung, Projekttitel. "
    "Suche in Kopfzeilen wie 'Projekt: ...', 'Bauvorhaben: ...', 'Objekt: ...' "
    "oder im Titel/Betreff des Dokuments)\n"
    "- objekt_nr: string | null (Objekt-/Projektnummer, Vergabenummer, Ausschreibungsnummer)\n"
    "- submission_date: string | null (Submissionsdatum/Angebotsfrist im Format TT.MM.JJJJ)\n"
    "- auftraggeber: string | null (Name der auftraggebenden Organisation/Firma/Behörde/Kommune, "
    "NICHT der persönliche Name des Bauherrn)\n"
    "- kunde_name: string | null (Name des Unternehmens das die Anfrage/Ausschreibung stellt)\n"
    "- kunde_adresse: string | null (Adresse des Absenders/Anfragenden)\n\n"
    "WICHTIG: Das beigefuegte PDF ist die einzige Informationsquelle. Ignoriere Fuss-/Kopfzeilen "
    "mit Firmennamen (z.B. 'GmbH & Co. KG') — das ist KEIN Rohrsystem und KEIN Metadatum-Auftraggeber "
    "ausser es ist explizit als solcher gekennzeichnet.\n\n"
    "Gib EIN JSON-Objekt zurueck mit genau dieser Struktur:\n"
    "{\n"
    '  "metadata": { ... Metadata-Felder wie oben ... },\n'
    '  "positions": [ ... Array von Positionen wie oben definiert ... ]\n'
    "}\n"
    "Gib NUR das JSON-Objekt zurueck, keine Erklaerung."
)


def _call_gemini_parse_pdf(pdf_bytes: bytes) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Single-shot LV parse: send PDF directly to Gemini, get positions + metadata.

    Returns (positions, metadata) where positions is the raw list of dicts from the
    model and metadata is a dict of project metadata fields.
    """
    if not settings.gemini_api_key:
        raise InterpretationError("GEMINI_API_KEY not configured")

    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
    payload = {
        "system_instruction": {"parts": [{"text": COMBINED_SYSTEM_INSTRUCTION}]},
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": "application/pdf", "data": pdf_b64}},
                {"text": "Analysiere das beigefuegte LV-PDF und gib das kombinierte JSON-Objekt zurueck."},
            ],
        }],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    data = _post_gemini(payload, timeout=180)
    try:
        content = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise InterpretationError(f"Unexpected Gemini response format: {data}") from exc

    try:
        normalized = _normalize_json_content(content)
        parsed = json.loads(normalized)
    except (json.JSONDecodeError, InterpretationError) as exc:
        raise InterpretationError(f"Invalid JSON returned by model: {exc}") from exc

    if not isinstance(parsed, dict):
        raise InterpretationError("Gemini did not return a JSON object")

    positions_raw = parsed.get("positions")
    if not isinstance(positions_raw, list):
        raise InterpretationError("Gemini response missing 'positions' array")

    metadata_raw = parsed.get("metadata") or {}
    if not isinstance(metadata_raw, dict):
        metadata_raw = {}

    return positions_raw, metadata_raw


_CONTINUATION_PATTERNS = (
    "leistungsbeschreibung auf voranstehender seite",
    "leistungsbeschreibung auf vorhergehender seite",
    "fortsetzung von seite",
    "übertrag",
)


def extract_raw_text_pages(pdf_bytes: bytes) -> list[str]:
    """Extract raw text per page using pdfplumber.

    Detects page-continuation patterns (e.g. 'Leistungsbeschreibung auf
    voranstehender Seite') and appends the continuation text to the previous
    page so that positions spanning a page break are kept together.
    """
    raw_pages: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                if text.strip():
                    raw_pages.append(text)
    except Exception as exc:
        logger.warning("pdfplumber raw text extraction failed, falling back to pypdf: %s", exc)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                raw_pages.append(text)

    if not raw_pages:
        return raw_pages

    # Merge continuation pages into the previous page
    merged: list[str] = [raw_pages[0]]
    for page_text in raw_pages[1:]:
        lines = page_text.strip().split("\n")
        # Skip header lines (Architekt, Objekt, POS. LEISTUNGSBESCHREIBUNG etc.)
        content_start = 0
        for i, line in enumerate(lines):
            stripped = line.strip().lower()
            if any(pat in stripped for pat in _CONTINUATION_PATTERNS):
                content_start = i
                break
        if content_start > 0:
            # Found continuation — extract the continuation block (up to next position)
            continuation_lines = lines[content_start:]
            # Find where actual new positions start (line starting with a position number)
            import re
            merge_end = len(continuation_lines)
            for j, cline in enumerate(continuation_lines):
                # A new position starts with a number like "04.0016" at the beginning
                if j > 0 and re.match(r"^\s*\d{2}\.\d{4}\s", cline):
                    merge_end = j
                    break

            # Append continuation to previous page
            merged[-1] += "\n" + "\n".join(continuation_lines[:merge_end])
            # Rest of page (new positions) stays as a new page
            remaining = "\n".join(lines[:content_start]) + "\n" + "\n".join(continuation_lines[merge_end:])
            if remaining.strip():
                merged.append(remaining)
        else:
            merged.append(page_text)

    return merged


def _to_float(value: Any) -> float | None:
    """Safely convert a value to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", ".").replace(" ", "")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


_ARTICLE_VERB_SUFFIX_RE = re.compile(
    r"\s+(?:liefern(?:\s+und\s+\w+)?|setzen|verlegen|herstellen|einbauen|montieren"
    r"|ausfugen|verfugen|anbringen|versetzen)\b\.?\s*$",
    re.IGNORECASE,
)


def _normalize_article_type(value: Any, position_type: str) -> str | None:
    """Strip trailing installation verbs from article_type when position is material."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return None
    if position_type != "material":
        return stripped
    cleaned = _ARTICLE_VERB_SUFFIX_RE.sub("", stripped).strip()
    return cleaned or stripped


def _to_string_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        return items or None
    if isinstance(value, str):
        items = [piece.strip() for piece in re.split(r"[,;/]", value) if piece.strip()]
        return items or None
    return None


def _normalize_spec_key(text: str) -> str:
    """Normalize a feature/spec string for cross-field duplicate detection."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _assemble_position(idx: int, raw: dict[str, Any]) -> LVPosition:
    """Convert a raw LLM dict into an LVPosition."""
    pos_type = raw.get("position_type", "material")
    if pos_type not in ("material", "dienstleistung"):
        pos_type = "material"

    quantity = _to_float(raw.get("quantity"))
    unit = raw.get("unit")
    description = raw.get("description", "")

    params = TechnicalParameters(
        article_type=_normalize_article_type(raw.get("article_type"), pos_type),
        product_category=raw.get("product_category"),
        product_subcategory=raw.get("product_subcategory"),
        material=raw.get("material"),
        nominal_diameter_dn=raw.get("nominal_diameter_dn"),
        secondary_nominal_diameter_dn=raw.get("secondary_nominal_diameter_dn"),
        load_class=raw.get("load_class"),
        norm=raw.get("norm"),
        dimensions=raw.get("dimensions"),
        color=raw.get("color"),
        quantity=quantity,
        unit=unit,
        reference_product=raw.get("reference_product"),
        installation_area=raw.get("installation_area"),
        stiffness_class_sn=raw.get("stiffness_class_sn"),
        sortiment_relevant=raw.get("sortiment_relevant"),
        system_family=raw.get("system_family"),
        connection_type=raw.get("connection_type"),
        seal_type=raw.get("seal_type"),
        compatible_systems=_to_string_list(raw.get("compatible_systems")),
        variants=_to_string_list(raw.get("variants")),
        features=_to_string_list(raw.get("features")),
        installation_notes=raw.get("installation_notes"),
        compressive_strength=raw.get("compressive_strength"),
        exposition_class=raw.get("exposition_class"),
        additional_specs=_to_string_list(raw.get("additional_specs")),
    )

    # Dedup: a qualifier may only appear once across features/additional_specs.
    # Material/Pruefeigenschaften (additional_specs) win over features.
    if params.features and params.additional_specs:
        spec_keys = {_normalize_spec_key(s) for s in params.additional_specs}
        deduped = [f for f in params.features if _normalize_spec_key(f) not in spec_keys]
        params.features = deduped or None

    return LVPosition(
        id=f"pos-{idx}",
        ordnungszahl=raw.get("ordnungszahl", f"?.{idx}"),
        description=description,
        raw_text=description,
        quantity=quantity,
        unit=unit,
        billable=pos_type == "material",
        position_type=pos_type,
        parameters=params,
        source_page=raw.get("source_page"),
    )


_VALID_CATEGORIES = {
    "kanalrohre", "schachtabdeckungen", "schachtbauteile", "formstuecke",
    "formstücke", "strassenentwässerung", "strassenentwaesserung", "rinnen",
    "dichtungen & zubehoer", "dichtungen & zubehör", "geotextilien",
    "gasrohre", "wasserrohre", "druckrohre", "kabelschutz",
}

_CLIENT_PROVIDED_RE = re.compile(
    r"(?:wird\s+(?:durch|vom)\s+(?:den\s+)?AG\b.*?gestellt"
    r"|ab\s+Lager\s+(?:des\s+)?AG\b"
    r"|beigestellt"
    r"|vom\s+AG\s+bereitgestellt"
    r"|AG\s+ab\s+Lager\b.*?gestellt)",
    re.IGNORECASE,
)

_REFERENCE_TO_PREVIOUS_RE = re.compile(
    r"^\s*(wie\s+zuvor|wie\s+position|wie\s+vorstehend|wie\s+vorhergehend)",
    re.IGNORECASE,
)

_STRUCTURAL_PARAM_FIELDS = (
    "article_type",
    "product_category",
    "product_subcategory",
    "material",
    "nominal_diameter_dn",
    "secondary_nominal_diameter_dn",
    "load_class",
    "norm",
    "dimensions",
    "reference_product",
    "installation_area",
    "stiffness_class_sn",
    "system_family",
    "connection_type",
    "seal_type",
    "compatible_systems",
)


def _is_reference_position(position: LVPosition) -> bool:
    text = f"{position.description}\n{position.raw_text}".strip()
    return bool(_REFERENCE_TO_PREVIOUS_RE.match(text))


def _inherit_reference_context(positions: list[LVPosition]) -> list[LVPosition]:
    inherited: list[LVPosition] = []
    previous_material: LVPosition | None = None

    for position in positions:
        current = position
        if current.position_type == "material" and _is_reference_position(current) and previous_material:
            merged = current.parameters.model_dump()
            base = previous_material.parameters.model_dump()
            inferred_base = _infer_with_heuristics(previous_material).model_dump()
            # Detect if the current position has a different material than the base
            cur_mat = (merged.get("material") or "").lower()
            base_mat = (base.get("material") or inferred_base.get("material") or "").lower()
            material_changed = cur_mat and base_mat and cur_mat != base_mat
            # Fields that should NOT be inherited across material boundaries
            _MATERIAL_BOUND_FIELDS = {"stiffness_class_sn", "norm", "system_family", "connection_type", "seal_type", "compatible_systems"}
            # For "wie zuvor" positions, category/subcategory from base take priority
            # because the LLM often misclassifies these minimal-text positions.
            # Prefer heuristic values for these fields since heuristics are grounded in text keywords.
            _INHERIT_OVERRIDE_FIELDS = {"product_category", "product_subcategory"}
            for field in _STRUCTURAL_PARAM_FIELDS:
                base_value = base.get(field)
                if base_value in (None, "", []) or (field in _INHERIT_OVERRIDE_FIELDS and inferred_base.get(field)):
                    inferred_val = inferred_base.get(field)
                    if inferred_val not in (None, "", []):
                        base_value = inferred_val
                # Don't inherit SN/norm/system across material changes
                if material_changed and field in _MATERIAL_BOUND_FIELDS:
                    continue
                if base_value not in (None, "", []):
                    if merged.get(field) in (None, "", []) or field in _INHERIT_OVERRIDE_FIELDS:
                        merged[field] = base_value
            current = current.model_copy(update={"parameters": TechnicalParameters(**merged)})

        inherited.append(current)
        if current.position_type == "material":
            previous_material = current

    return inherited


def _merge_heuristic_parameters(position: LVPosition, heuristic_params: TechnicalParameters) -> TechnicalParameters:
    merged = position.parameters.model_dump()
    is_reference = _is_reference_position(position)
    category_conflict = (
        heuristic_params.product_category
        and merged.get("product_category")
        and heuristic_params.product_category != merged.get("product_category")
    )
    subcategory_conflict = (
        heuristic_params.product_subcategory
        and merged.get("product_subcategory")
        and heuristic_params.product_subcategory != merged.get("product_subcategory")
    )

    if is_reference or category_conflict or subcategory_conflict:
        for field in _STRUCTURAL_PARAM_FIELDS:
            value = getattr(heuristic_params, field)
            if value not in (None, "", []):
                merged[field] = value
    else:
        for key, value in heuristic_params.model_dump().items():
            if merged.get(key) is None and value not in (None, "", []):
                merged[key] = value

    return TechnicalParameters(**merged)


def _is_service_by_heuristic(pos: LVPosition) -> bool:
    """Check if a position classified as 'material' by LLM is actually a service/labor position."""
    text = f"{pos.description}\n{pos.raw_text}".lower()

    # Positions with DN or load class have a strong product signal — don't reclassify
    from .ai_interpreter import DN_RE, LOAD_CLASSES
    if DN_RE.search(pos.raw_text or ""):
        return False
    if any(lc.lower() in text for lc in LOAD_CLASSES):
        return False

    # "Zulage" = price surcharge for labor, not a standalone product
    if re.match(r"^\s*zulage\b", text):
        return True

    # Cutting/bearbeiten services: verb "schneiden/kürzen/zuschneiden/ausklinken"
    # combined with "Bruchmaterial entsorgen" signals a pure labor position — even if
    # "Materiallieferungen" is mentioned (usually refers to Verschleissmaterial).
    # Only material if the position ITSELF specifies a new Werkstoff (e.g. "aus Beton").
    _CUTTING_VERB_RE = re.compile(
        r"\b(schneiden|zuschneiden|k[uü]rzen|ausklinken|nachbearbeiten)\b",
        re.IGNORECASE,
    )
    _BRUCHMATERIAL_RE = re.compile(r"bruchmaterial.*entsorg|bruchmaterial\s+ist", re.IGNORECASE)
    _OWN_MATERIAL_SPEC_RE = re.compile(
        r"\baus\s+(beton|stahlbeton|polymerbeton|kunststoff|pvc|pp\b|pe\b|gusseisen|steinzeug|naturstein)\b",
        re.IGNORECASE,
    )
    if _CUTTING_VERB_RE.search(text) and _BRUCHMATERIAL_RE.search(text):
        if not _OWN_MATERIAL_SPEC_RE.search(text):
            return True

    # Service keywords that override material classification
    _SERVICE_OVERRIDE_KEYWORDS = (
        "kopfloch", "anschlussarbeiten",
        "schnittkanten", "schnitt ausklinkung",
        "plattendruckversuch", "lastplattendruck", "druckversuch",
        "regulieren", "höhenanpass", "hoehen",
        "tragschicht", "überarbeiten", "ueberarbeiten",
    )
    if any(kw in text for kw in _SERVICE_OVERRIDE_KEYWORDS):
        return True

    return False


def _post_process_positions(positions: list[LVPosition]) -> list[LVPosition]:
    """Thin post-processing over LLM output.

    Does NOT run heuristic parameter inference — trusts the LLM to fill fields
    directly from the PDF. Only applies safety-net reclassification, category
    whitelist sanitization, and `_post_merge_sanity` normalization to fix
    known LLM quirks (DA/DN confusion, category aliases, material overrides).
    """
    positions = _inherit_reference_context(positions)
    validated: list[LVPosition] = []
    for pos in positions:
        # Reclassify material→DL if material is provided by client (AG)
        # or if the position is clearly a service/labor position.
        reclassify_as_dl = False
        if pos.position_type == "material":
            if _CLIENT_PROVIDED_RE.search(pos.description or ""):
                logger.info("Reclassifying %s→DL (material provided by client)", pos.ordnungszahl)
                reclassify_as_dl = True
            elif _is_service_by_heuristic(pos):
                logger.info("Reclassifying %s→DL (service keywords detected)", pos.ordnungszahl)
                reclassify_as_dl = True

        if reclassify_as_dl:
            pos = pos.model_copy(update={
                "position_type": "dienstleistung",
                "billable": False,
                "parameters": TechnicalParameters(
                    article_type=pos.parameters.article_type,
                    product_category=None, product_subcategory=None,
                    material=None, nominal_diameter_dn=None,
                    secondary_nominal_diameter_dn=None,
                    load_class=None, norm=None, dimensions=None,
                    color=None, quantity=pos.quantity, unit=pos.unit,
                    reference_product=None, installation_area=None,
                    system_family=None, connection_type=None,
                    seal_type=None, compatible_systems=None,
                ),
            })

        if pos.position_type == "dienstleistung":
            validated.append(pos)
            continue

        # Sanitize invalid categories from LLM output
        cat = pos.parameters.product_category
        if cat and cat.lower() not in _VALID_CATEGORIES:
            logger.info(
                "Stripping invalid category '%s' from %s '%s'",
                cat, pos.ordnungszahl, pos.description[:60],
            )
            pos = pos.model_copy(update={
                "parameters": pos.parameters.model_copy(update={"product_category": None}),
            })

        pos = _maybe_reclassify_as_material(pos)
        cleaned = _post_merge_sanity(pos.parameters, pos)
        validated.append(pos.model_copy(update={"parameters": cleaned}))
    return validated


_OZ_LINE_RE = re.compile(r"^\s*(\d+(?:\.\d+)+)\.?\s")


def _normalize_oz(value: str) -> str:
    """Normalize ordnungszahl tokens for robust matching (e.g. 04.0010. -> 4.10)."""
    stripped = value.strip().rstrip(".,:;")
    stripped = re.sub(r"[^0-9.]", "", stripped)
    stripped = re.sub(r"\.{2,}", ".", stripped).strip(".")
    if "." not in stripped:
        return stripped
    parts = [part for part in stripped.split(".") if part]
    normalized_parts: list[str] = []
    for part in parts:
        try:
            normalized_parts.append(str(int(part)))
        except ValueError:
            normalized_parts.append(part)
    return ".".join(normalized_parts)


def _map_oz_to_page(pdf_bytes: bytes, ordnungszahlen: list[str]) -> dict[str, int]:
    """Find the actual 1-based PDF page number for each ordnungszahl."""
    candidates = _collect_oz_candidates(pdf_bytes, ordnungszahlen)
    result: dict[str, int] = {}
    for oz in ordnungszahlen:
        key = _normalize_oz(oz)
        best = _choose_best_oz_candidate(candidates.get(key, []))
        if best:
            result[oz] = best[0]
    return result


def _map_oz_to_anchor_top(pdf_bytes: bytes, ordnungszahlen: list[str]) -> dict[str, int]:
    """Find vertical anchor offsets (top) for each ordnungszahl on its page."""
    candidates = _collect_oz_candidates(pdf_bytes, ordnungszahlen)
    result: dict[str, int] = {}
    for oz in ordnungszahlen:
        key = _normalize_oz(oz)
        best = _choose_best_oz_candidate(candidates.get(key, []))
        if not best:
            continue
        # Lift view a bit so headline/line context is visible immediately.
        result[oz] = max(0, int(best[1]) - 24)
    return result


def _collect_oz_candidates(
    pdf_bytes: bytes,
    ordnungszahlen: list[str],
) -> dict[str, list[tuple[int, float, float]]]:
    wanted_keys = {_normalize_oz(oz) for oz in ordnungszahlen if _normalize_oz(oz)}
    candidates: dict[str, list[tuple[int, float, float]]] = {key: [] for key in wanted_keys}
    if not wanted_keys:
        return candidates

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False) or []
            for word in words:
                raw = str(word.get("text") or "")
                key = _normalize_oz(raw)
                if key not in wanted_keys:
                    continue
                top_raw = word.get("top")
                x0_raw = word.get("x0")
                try:
                    top = float(top_raw) if top_raw is not None else 0.0
                except (TypeError, ValueError):
                    top = 0.0
                try:
                    x0 = float(x0_raw) if x0_raw is not None else 0.0
                except (TypeError, ValueError):
                    x0 = 0.0
                candidates[key].append((page_num, top, x0))
    return candidates


def _choose_best_oz_candidate(
    options: list[tuple[int, float, float]],
) -> tuple[int, float, float] | None:
    if not options:
        return None
    # OZ labels are usually in the left OZ column; prefer those hits.
    left_column = [opt for opt in options if opt[2] <= 150.0]
    pool = left_column or options
    pool.sort(key=lambda item: (item[0], item[2], item[1]))
    return pool[0]
_SKIP_LINE_RE = re.compile(
    r"^\s*(Architekt|Objekt\s*:|Bauherr|Seite\s+\d|LEISTUNGSVERZEICHNIS|"
    r"Leistungsbeschreibung auf vo|POS\.\s|---|"
    r"[Üü]bertrag:?\s*$|Bauvorhaben:\s*\d|Projekt-Nr\.|Ausschr\.-Nr\.|"
    r"Pos-Nr\.\s+Menge\s+ME|EP\s*/\s*EUR|GP\s*/\s*EUR|Datum:\s*\d)",
    re.IGNORECASE,
)

_PAGE_BOILERPLATE_RE = re.compile(
    r"^\s*(?:"
    r"Angebotsaufforderung\s*$|"
    r"Zusammenstellung\s*$|"
    r"Projekt\s*:|"
    r"LV\s*:|"
    r"Leistungsbereich\s*:|"
    r"W[aä]hrung\s*:|"
    r"Ordnungszahl\s+Leistungsbeschreibung\b|"
    r"Summe\s+(?:\d+\.|LV\s+\d)|"
    r"Seite\s*[:]\s*\d"
    r")",
    re.IGNORECASE,
)

_DESCRIPTION_METADATA_LINE_RE = re.compile(
    r"^\s*(?:"
    r"\.?\s*stl\s*[-.]?\s*nr\b|"
    r"l\s*eistungsbereich\s*:|"
    r"projekt:|"
    r"lv:|"
    r"angebotsaufforderung\b|"
    r"ordnungszahl\s+leistungsbeschreibung\b|"
    r"menge\s+me\b|"
    r"einheitspreis\b|"
    r"gesamtbetrag\b|"
    r"in\s+eur\b|"
    r"seite\s*:?\s*\d+\b|"
    r"[üu]bertrag:?\b"
    r")",
    re.IGNORECASE,
)


def _join_wrapped_paragraphs(raw_text: str) -> list[str]:
    """Merge PDF-wrapped line fragments into logical paragraphs.

    PDF text extraction tends to break sentences at visual line wrap. Here we
    re-stitch fragments that end mid-sentence so downstream detail extractors
    don't produce clause fragments like "selbstnivellierenden Rahmen unterfuettern und".
    Lines that start with a capital + colon label (e.g. "Abmessungen B/H/L") or a
    clear new clause are treated as new paragraphs.
    """
    label_start_re = re.compile(
        r"^(?:Abmessung(?:en)?|Ausf[uü]hrung|Farb[et]|Fundament|Bettung|"
        r"R[uü]ckenst[uü]tze|Kurvenradien|Typ|Klasse|Norm|Anschluss|Material|"
        r"Form\s+[A-Z])",
        re.IGNORECASE,
    )
    paragraphs: list[str] = []
    current = ""
    for raw in raw_text.split("\n"):
        stripped = raw.strip()
        if not stripped:
            if current:
                paragraphs.append(current)
                current = ""
            continue
        starts_new = bool(label_start_re.match(stripped)) or (current == "")
        ends_sentence = current.rstrip().endswith((".", ";", ":", "!", "?"))
        if current and not ends_sentence and not starts_new:
            current += " " + stripped
        else:
            if current:
                paragraphs.append(current)
            current = stripped
    if current:
        paragraphs.append(current)
    return paragraphs


def _derive_description_from_raw_text(raw_text: str, fallback: str | None = None) -> str:
    """Build a stable short description directly from the original LV block.

    This avoids shifted LLM summaries when the model assigns the next position's
    header to the current OZ. Keep the first meaningful 1-2 lines and prefer the
    more complete variant when the first line is only a truncated duplicate.
    """
    if not raw_text:
        return fallback or ""

    candidates: list[str] = []
    quantity_line_re = re.compile(
        r"^\s*[\d.,]+\s+(Stück|Stck|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b",
        re.IGNORECASE,
    )
    technical_line_re = re.compile(
        r"(dn\s*\d+|sn\s*\d+|din|d[0-9]{3}|[0-9]+\s*(mm|cm|m)\b|"
        r"[0-9]+\s*/\s*[0-9]+|[0-9]+\s*x\s*[0-9]+|"
        r"beton|stahlbeton|pp\b|pvc|pe\b|pe-?hd|steinzeug|polymerbeton|"
        r"naturstein|basalt|dr[aä]nmatte|richtzeichnung|radius|typ\s+[a-z0-9]+|"
        r"[0-9]+\s*-\s*zeilig|[0-9]+\s*zeilig|muldenrinne|pultform|kugelgelenk)",
        re.IGNORECASE,
    )
    generic_line_re = re.compile(
        r"(nach unterlagen des ag|liefern und einbauen|fachgerecht herstellen|"
        r"abgerechnet wird|bauwerken nach|herstellen\.$)",
        re.IGNORECASE,
    )

    def _normalize_fragment(value: str) -> str:
        normalized = re.sub(r"\s+", " ", value).strip(" ,;")
        normalized = re.sub(r"\s+([,.;:/])", r"\1", normalized)
        normalized = re.sub(r"(?<=\d)\s+(?=\d)", "", normalized)
        normalized = re.sub(r"(?<=\bDN)\s+(?=\d)", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"(?<=\bSN)\s+(?=\d)", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b([0-9]+)\s*-\s*zeilig\b", r"\1-zeilig", normalized, flags=re.IGNORECASE)
        return normalized

    for line in _join_wrapped_paragraphs(raw_text):
        stripped = line.strip()
        if not stripped:
            continue
        if _SKIP_LINE_RE.match(stripped):
            continue
        if _DESCRIPTION_METADATA_LINE_RE.match(stripped):
            continue
        if quantity_line_re.match(stripped):
            continue
        candidates.append(stripped)
        if len(candidates) >= 12:
            break

    if not candidates:
        return fallback or raw_text.strip()

    deduped: list[str] = []
    for line in candidates:
        normalized = _normalize_fragment(line)
        if any(
            normalized == existing
            or normalized in existing
            or existing in normalized
            for existing in deduped
        ):
            if deduped and len(normalized) > len(deduped[-1]) and (
                normalized.startswith(deduped[-1]) or deduped[-1].startswith(normalized)
            ):
                deduped[-1] = normalized
            continue
        deduped.append(normalized)

    if not deduped:
        return fallback or raw_text.strip()

    title = deduped[0]
    details: list[str] = []
    for line in deduped[1:]:
        if generic_line_re.search(line):
            continue
        if not technical_line_re.search(line):
            continue
        if line.lower() in title.lower() or title.lower() in line.lower():
            continue
        details.append(line)
        if len(details) >= 2:
            break

    if details:
        return f"{title}, {', '.join(details)}"[:200]

    return title[:200]


def _is_bad_display_description(value: str | None) -> bool:
    if not value:
        return True
    stripped = value.strip()
    if not stripped:
        return True
    lowered = stripped.lower()
    return bool(
        _DESCRIPTION_METADATA_LINE_RE.match(stripped)
        or lowered.startswith("wie zuvor")
        or lowered.startswith("wie position")
        or lowered.startswith("übertrag")
    )


def _human_label_from_params(params: TechnicalParameters) -> str | None:
    subcategory = (params.product_subcategory or "").strip().lower()
    category = (params.product_category or "").strip().lower()
    mapping = {
        "rohr": "Rohr",
        "kanalrohr": "Abwasserkanal",
        "bogen": "Rohrbogen",
        "abzweig": "Abzweig",
        "reduzierstück": "Reduzierstück",
        "reduzierstueck": "Reduzierstück",
        "muffe": "Muffe",
        "muffenstopfen": "Muffenstopfen",
        "revisionsstück": "Reinigungsrohr",
        "revisionsstueck": "Reinigungsrohr",
        "revisionsschacht": "Entwässerungsschacht",
        "schachtunterteil": "Schachtunterteil",
        "schachtring": "Schachtring",
        "konus": "Schachtkonus",
        "ausgleichsring": "Ausgleichsring",
        "schachtfutter": "Schachtfutter",
        "ablauf": "Straßenablauf",
        "aufsatz": "Aufsatz",
        "einlaufkasten": "Einlaufkasten",
        "rinne": "Entwässerungsrinne",
        "abdeckung": "Schachtabdeckung",
        "anschlusssystem": "Anschlusssystem",
        "dränschicht": "Dränschicht",
        "dränmatte": "Dränschicht",
        "dränrohr": "Dränrohr",
    }
    if subcategory in mapping:
        return mapping[subcategory]
    category_mapping = {
        "kanalrohre": "Abwasserkanal",
        "schachtabdeckungen": "Schachtabdeckung",
        "schachtbauteile": "Schachtbauteil",
        "formstuecke": "Formteil",
        "formstücke": "Formteil",
        "straßenentwässerung": "Straßenentwässerung",
        "strassenentwässerung": "Straßenentwässerung",
        "strassenentwaesserung": "Straßenentwässerung",
        "rinnen": "Entwässerungsrinne",
        "dichtungen & zubehoer": "Zubehör",
        "dichtungen & zubehör": "Zubehör",
        "geotextilien": "Geotextil",
        "gasrohre": "Gasrohr",
        "wasserrohre": "Wasserrohr",
        "druckrohre": "Druckrohr",
        "kabelschutz": "Kabelschutzrohr",
    }
    return category_mapping.get(category)


def _append_unique_detail(details: list[str], value: str | None, existing: str) -> None:
    if not value:
        return
    cleaned = re.sub(r"\s+", " ", value).strip(" ,;")
    if not cleaned:
        return
    def _canonical(text: str) -> str:
        text = re.sub(r"^[A-Za-zÄÖÜäöüß /+-]+:\s*", "", text).strip()
        text = re.sub(r"[^a-z0-9äöüß]+", "", text.lower())
        return text
    lowered_existing = existing.lower()
    lowered_cleaned = cleaned.lower()
    canonical_cleaned = _canonical(cleaned)
    canonical_existing = _canonical(existing)
    if lowered_cleaned in lowered_existing or canonical_cleaned in canonical_existing:
        return
    if any(_canonical(item) == canonical_cleaned for item in details):
        return
    details.append(cleaned)


def _extract_signal_details_from_raw(raw_text: str, title: str, limit: int = 2) -> list[str]:
    lines = [line.strip() for line in _join_wrapped_paragraphs(raw_text) if line.strip()]
    if not lines:
        return []

    quantity_line_re = re.compile(
        r"^\s*[\d.,]+\s+(Stück|Stck|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b",
        re.IGNORECASE,
    )
    labeled_detail_re = re.compile(
        r"^(abmessungen|maße|masse|material|klasse|belastungsklasse|dicke|stärke|breite|höhe|"
        r"länge|farbton|farbe|typ|anschlussrohr|ablauf|einlaufkasten|stichmaß|stichmass|"
        r"fundament|bettung|gummiauflage|schlammeimer|filtersack)\s*:?\s+(.+)$",
        re.IGNORECASE,
    )
    installation_signal_re = re.compile(
        r"\b(adapterring|ausgleichsring|rahmen|selbstnivell|unterfütter|unterfuetter|einwalz|"
        r"mörtel|moertel|mg\s*[ivx]+|beton\s*c\s*\d{1,2}\s*/\s*\d{1,2}|rückenstütze|rueckenstuetze|"
        r"fundament|bettung|nassschnitt|entsorg|abdicht|schmutzfänger|schmutzfaenger)\b",
        re.IGNORECASE,
    )

    details: list[str] = []
    normalized_title = re.sub(r"\s+", " ", title).strip().lower()
    for raw_line in lines[1:]:
        if _SKIP_LINE_RE.match(raw_line) or _DESCRIPTION_METADATA_LINE_RE.match(raw_line):
            continue
        if quantity_line_re.match(raw_line):
            continue
        normalized = re.sub(r"\s+", " ", raw_line).strip(" ,;")
        normalized = re.sub(r"\s+([,.;:/])", r"\1", normalized)
        if not normalized:
            continue
        if normalized.lower() in normalized_title or normalized_title in normalized.lower():
            continue
        match = labeled_detail_re.match(normalized)
        if match:
            label = match.group(1).strip()
            value = match.group(2).strip()
            _append_unique_detail(details, f"{label}: {value}", title)
        else:
            # Also keep unlabeled but technically relevant installation details.
            if not installation_signal_re.search(normalized):
                continue
            if "," in normalized:
                parts = [part.strip() for part in normalized.split(",") if part.strip()]
                if len(parts) > 1:
                    first = parts[0].lower()
                    if first in normalized_title or normalized_title in first:
                        normalized = ", ".join(parts[1:])
            _append_unique_detail(details, normalized, title)
        if len(details) >= limit:
            break
    return details


def _build_display_description(
    position: LVPosition,
    previous_material_description: str | None = None,
) -> str:
    fallback = position.description
    base = _derive_description_from_raw_text(position.raw_text, fallback)
    params = position.parameters

    fallback_clean = re.sub(r"\s+", " ", fallback or "").strip(" ,;")
    title = fallback_clean if fallback_clean and not _is_bad_display_description(fallback_clean) else base

    human_label = _human_label_from_params(params)
    if _is_bad_display_description(title):
        if previous_material_description and not _is_bad_display_description(previous_material_description):
            title = previous_material_description.split(",")[0].strip()
        elif human_label:
            title = human_label

    title = re.sub(r"\s+", " ", title).strip(" ,;")
    if not title:
        title = fallback_clean or "Position"

    details: list[str] = []
    # Prioritize technically relevant raw-text hints (e.g. adapter rings, mortar class,
    # underfilling/installation constraints) so they are not lost in fallback truncation.
    for raw_detail in _extract_signal_details_from_raw(position.raw_text, title, limit=3):
        _append_unique_detail(details, raw_detail, title)

    if params.nominal_diameter_dn is not None and params.secondary_nominal_diameter_dn is not None:
        _append_unique_detail(details, f"DN {params.nominal_diameter_dn}/{params.secondary_nominal_diameter_dn}", title)
    elif params.nominal_diameter_dn is not None:
        _append_unique_detail(details, f"DN {params.nominal_diameter_dn}", title)
    if params.material:
        _append_unique_detail(details, params.material, title)
    if params.stiffness_class_sn is not None:
        _append_unique_detail(details, f"SN{params.stiffness_class_sn}", title)
    if params.norm:
        _append_unique_detail(details, params.norm, title)
    if params.load_class:
        _append_unique_detail(details, params.load_class, title)
    if params.dimensions:
        _append_unique_detail(details, params.dimensions, title)
    if params.system_family and (_is_bad_display_description(fallback_clean) or human_label):
        _append_unique_detail(details, params.system_family, title)
    if params.reference_product and "z. b." not in title.lower():
        _append_unique_detail(details, f"z. B. {params.reference_product}", title)

    if details:
        return f"{title}, {', '.join(details)}"[:320]
    return title[:320]


def finalize_position_descriptions(positions: list[LVPosition]) -> list[LVPosition]:
    finalized: list[LVPosition] = []
    previous_material_description: str | None = None
    for position in positions:
        if position.position_type == "dienstleistung":
            description = _derive_description_from_raw_text(position.raw_text, position.description)
        else:
            description = _build_display_description(position, previous_material_description)
        updated = position.model_copy(update={"description": description})
        finalized.append(updated)
        if updated.position_type == "material":
            previous_material_description = description
    return finalized


def _extract_raw_texts_from_pages(
    pages: list[str], ordnungszahlen: list[str],
) -> dict[str, str]:
    """Extract the original LV text for each position by finding its ordnungszahl in the PDF pages.

    Returns a dict mapping ordnungszahl → raw text block from the PDF.
    """
    full_text = "\n".join(pages)
    lines = full_text.split("\n")

    # Find ALL OZ-like line starts in the full text
    all_oz_lines: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = _OZ_LINE_RE.match(line)
        if m:
            oz_candidate = m.group(1)
            # Must have at least one dot and look like an OZ (not page numbers etc.)
            if "." in oz_candidate:
                all_oz_lines.append((i, oz_candidate))
    wanted = set(ordnungszahlen)

    result: dict[str, str] = {}
    for idx, (start_line, oz) in enumerate(all_oz_lines):
        if oz not in wanted:
            continue

        # End is start of next OZ line (any OZ)
        if idx + 1 < len(all_oz_lines):
            end_line = all_oz_lines[idx + 1][0]
        else:
            end_line = min(start_line + 30, len(lines))

        # Collect description lines — skip headers, dotted lines, blank filler
        block_lines: list[str] = []
        for j in range(start_line, end_line):
            line = lines[j]
            # First line: strip the OZ prefix, keep description text if present
            if j == start_line:
                # Remove OZ number from start of line
                stripped = _OZ_LINE_RE.sub("", line, count=1).strip()
                # If what remains is just quantity + underscores, skip entirely
                if not stripped or "________" in stripped or re.match(r"^[\d.,]+\s+(Stück|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\s", stripped, re.IGNORECASE):
                    continue
                block_lines.append(stripped)
                continue
            if _SKIP_LINE_RE.match(line):
                continue
            if _DESCRIPTION_METADATA_LINE_RE.match(line):
                continue
            if _PAGE_BOILERPLATE_RE.match(line):
                continue
            # Skip dotted/underscore placeholder lines
            if "________" in line or ".................." in line:
                continue
            # Skip standalone quantity lines like "35,000 m ______"
            if re.match(r"^\s*[\d.,]+\s+(Stück|Stk|St|m2|m²|m3|m³|m|lfm|lfdm|lfd\.m|kg|to|t|h|Std|StD|Psch|psch|Pausch|Wo|mWo|cbm)\b", line, re.IGNORECASE):
                continue
            block_lines.append(line)

        # Trim trailing blank lines
        while block_lines and not block_lines[-1].strip():
            block_lines.pop()

        if block_lines:
            result[oz] = "\n".join(block_lines)

    return result


def parse_lv_with_llm(pdf_bytes: bytes) -> tuple[list[LVPosition], ProjectMetadata]:
    """Parse an LV PDF using a single Gemini call with direct PDF upload.

    Returns (positions, metadata) tuple.
    """
    raw_positions, raw_metadata = _call_gemini_parse_pdf(pdf_bytes)

    if not raw_positions:
        raise InterpretationError("LLM returned no positions")

    try:
        metadata = ProjectMetadata(**{k: v for k, v in raw_metadata.items() if v})
    except Exception as exc:
        logger.warning("Metadata parse failed: %s", exc)
        metadata = ProjectMetadata()

    # Sort by ordnungszahl
    def _sort_key(raw: dict[str, Any]) -> list[int]:
        oz = raw.get("ordnungszahl", "0")
        try:
            return [int(x) for x in oz.split(".")]
        except ValueError:
            return [999]

    raw_positions.sort(key=_sort_key)
    positions = [_assemble_position(idx, raw) for idx, raw in enumerate(raw_positions, start=1)]

    # Attach raw_text (pdfplumber-derived) and frontend navigation anchors.
    # Raw-text extraction still uses pdfplumber — needed for display-layer detail
    # extraction (dimensions, installation hints) and as input to post_merge_sanity.
    oz_list = [p.ordnungszahl for p in positions]
    try:
        pages = extract_raw_text_pages(pdf_bytes)
        raw_texts = _extract_raw_texts_from_pages(pages, oz_list) if pages else {}
    except Exception as exc:
        logger.warning("Raw-text extraction failed: %s", exc)
        raw_texts = {}

    try:
        oz_pages = _map_oz_to_page(pdf_bytes, oz_list)
        oz_tops = _map_oz_to_anchor_top(pdf_bytes, oz_list)
    except Exception as exc:
        logger.warning("OZ page mapping failed: %s", exc)
        oz_pages, oz_tops = {}, {}

    positions = [
        p.model_copy(update={
            **({"raw_text": raw_texts[p.ordnungszahl]} if p.ordnungszahl in raw_texts else {}),
            **({"source_page": oz_pages[p.ordnungszahl]} if p.ordnungszahl in oz_pages else {}),
            **({"source_y": oz_tops[p.ordnungszahl]} if p.ordnungszahl in oz_tops else {}),
        })
        for p in positions
    ]

    # Thin post-processing: reclassification safety net + normalization.
    positions = _post_process_positions(positions)
    positions = finalize_position_descriptions(positions)

    logger.info(
        "LLM parsing complete: %d positions (%d material, %d dienstleistung)",
        len(positions),
        sum(1 for p in positions if p.position_type == "material"),
        sum(1 for p in positions if p.position_type == "dienstleistung"),
    )

    return positions, metadata

    return positions, metadata
