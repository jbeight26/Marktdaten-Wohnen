#!/usr/bin/env python3
"""
Zwischen den Lesern und dem Speicher.

Die Tabellenleser bleiben, wie sie sind -- sie kennen ihre Berichte und sonst
nichts. Dieses Modul übersetzt in beide Richtungen:

    Leser  ->  Fakten  ->  Datenbank      (einlagern)
    Datenbank  ->  Fakten  ->  Ausgabe    (auslesen)

Der Nutzen dieser Trennung: die Ausgabe fragt nur noch die Datenbank. Ob ein
Wert vor fünf Minuten aus einem PDF kam oder vor zwei Jahren, sieht man ihm
nicht mehr an -- und muss man auch nicht.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable

import db
from db import Faktum

# Welche Felder eines Stadtteils welche Kennzahl ergeben. Hamburg führt in
# einer Tabelle mehrere Objektarten nebeneinander, deshalb die Zuordnung.
HH_FELDER = (
    # (Attribut, Markerattribut, Objektart, Kennzahl, Einheit)
    ("price",     "price_marker",     "etw", "preis",      "€/m²"),
    ("count",     "count_marker",     "etw", "kauffaelle", "Verkäufe"),
    ("factor",    None,               "etw", "faktor",     "Faktor"),
    ("mfh_count", "mfh_count_marker", "mfh", "verkaeufe",  "Verkäufe"),
    ("mfh_factor", None,              "mfh", "faktor",     "Faktor"),
)


# ===========================================================================
# Einlagern
# ===========================================================================

def hamburg_fakten(report, methode_je_jahr: dict[int, str] | None = None
                   ) -> list[Faktum]:
    """Alles aus einem Hamburger Bericht, als Fakten.

    `methode_je_jahr` merkt sich, welche Jahrgänge nur per Texterkennung
    lesbar waren. Das gehört an jeden einzelnen Wert, nicht in eine Fussnote:
    wer später eine Zahl zitiert, soll sehen, wie sie zustande kam.
    """
    methoden = methode_je_jahr or {}
    raus: list[Faktum] = []

    for jahrgang in report.years:
        jahr, bericht = jahrgang.data_year, jahrgang.report_year
        methode = methoden.get(jahr, "text")
        seiten = jahrgang.pages or {}

        for name, werte in jahrgang.areas.items():
            for attribut, marker_attr, objektart, kennzahl, einheit in HH_FELDER:
                wert = getattr(werte, attribut, None)
                marker = getattr(werte, marker_attr, None) if marker_attr else None
                if wert is None and marker is None:
                    continue
                raus.append(Faktum(
                    quelle=report.source_key, bericht=bericht, jahr=jahr,
                    ebene="gebiet", gebiet=name, segment="bestand",
                    objektart=objektart, kennzahl=kennzahl, wert=wert,
                    marker=marker, einheit=einheit,
                    seite=seiten.get("preis"), methode=methode,
                ))

        for schluessel, wert in (jahrgang.totals or {}).items():
            if wert is None:
                continue
            objektart = "mfh" if schluessel.startswith("mfh") else "etw"
            kennzahl = {"preis": "preis", "kauffaelle": "kauffaelle"}.get(
                schluessel, schluessel)
            raus.append(Faktum(
                quelle=report.source_key, bericht=bericht, jahr=jahr,
                ebene="stadt", gebiet="", segment="bestand",
                objektart=objektart, kennzahl=kennzahl, wert=wert,
                einheit="€/m²" if kennzahl == "preis" else "Verkäufe",
                methode=methode,
            ))

        # Baujahr x Lagequalität. Gebiet traegt hier die Baujahrsklasse,
        # Segment die Lage -- dieselben Spalten, andere Bedeutung.
        for baujahr, kennzahlen in (jahrgang.quality or {}).items():
            for kennzahl, lagen in kennzahlen.items():
                for lage, wert in (lagen or {}).items():
                    # Auch ohne Wert eine Zeile: die Matrix soll die Lücke
                    # zeigen, nicht die Spalte verschweigen. Ein fehlender
                    # Schlüssel und ein leerer Wert sind nicht dasselbe.
                    raus.append(Faktum(
                        quelle=report.source_key, bericht=bericht, jahr=jahr,
                        ebene="baujahr_lage", gebiet=baujahr, segment=lage,
                        objektart="etw", kennzahl=kennzahl.lower(), wert=wert,
                        einheit="€/m²", methode=methode,
                    ))

    bericht_neu = report.years[-1].report_year if report.years else 0

    for jahr, wert in report.index_series:
        raus.append(Faktum(quelle=report.source_key, bericht=bericht_neu,
                           jahr=jahr, ebene="stadt", kennzahl="index",
                           objektart="etw", wert=wert, einheit="Index"))
    for jahr, wert in report.index_series_mfh:
        raus.append(Faktum(quelle=report.source_key, bericht=bericht_neu,
                           jahr=jahr, ebene="stadt", kennzahl="index",
                           objektart="mfh", wert=wert, einheit="Index"))

    for eintrag in report.standard_flat:
        for feld, wert in eintrag.items():
            if feld == "year" or wert is None:
                continue
            # "altbau" ist der Gesamtkaufpreis, "altbau_sqm" der Quadratmeterwert.
            segment, _, zusatz = feld.partition("_")
            raus.append(Faktum(
                quelle=report.source_key, bericht=bericht_neu,
                jahr=eintrag["year"], ebene="stadt", segment=segment,
                objektart="etw",
                kennzahl="standardwohnung" + (f"_{zusatz}" if zusatz else ""),
                wert=wert, einheit="€/m²" if zusatz else "€", methode="text",
            ))

    return raus


def stadt_fakten(daten) -> list[Faktum]:
    """Eine Zusatzstadt (Wiesbaden, Kiel, Frankfurt) als Fakten."""
    raus: list[Faktum] = []
    jahrgaenge = daten.years or [None]

    for jahrgang in jahrgaenge:
        jahr = jahrgang.data_year if jahrgang else daten.data_year
        bericht = jahrgang.report_year if jahrgang else daten.report_year
        segmente = jahrgang.segments if jahrgang else daten.segments
        seite = _seitenzahl(jahrgang.source_page if jahrgang else daten.source_page)
        # Wiesbaden und Frankfurt rechnen ihre Gebietswerte aus Zellen -- das
        # ist etwas anderes als eine abgelesene Zahl und wird so vermerkt.
        methode = "gerechnet" if daten.key in ("wiesbaden", "frankfurt") else "text"

        for segment in segmente:
            for name, feld in segment.areas.items():
                wert, marker = feld.get("p"), feld.get("m")
                if wert is None and marker is None:
                    continue
                raus.append(Faktum(
                    quelle=daten.key, bericht=bericht, jahr=jahr, ebene="gebiet",
                    gebiet=name, segment=segment.key, objektart="etw",
                    kennzahl="preis", wert=wert, marker=marker,
                    einheit=segment.unit, seite=seite, methode=methode,
                ))
                for schluessel, kennzahl, einheit in (
                        ("c", "kauffaelle", "Verkäufe"),
                        ("baujahr", "baujahr", "Jahr"),
                        ("wohnflaeche", "wohnflaeche", "m²")):
                    if feld.get(schluessel) is None:
                        continue
                    raus.append(Faktum(
                        quelle=daten.key, bericht=bericht, jahr=jahr,
                        ebene="gebiet", gebiet=name, segment=segment.key,
                        objektart="etw", kennzahl=kennzahl, wert=feld[schluessel],
                        einheit=einheit, seite=seite, methode=methode,
                    ))
            if segment.total is not None:
                raus.append(Faktum(
                    quelle=daten.key, bericht=bericht, jahr=jahr, ebene="stadt",
                    segment=segment.key, objektart="etw", kennzahl="preis",
                    wert=segment.total, einheit=segment.unit, seite=seite,
                    methode=methode,
                ))
            if segment.total_count is not None:
                raus.append(Faktum(
                    quelle=daten.key, bericht=bericht, jahr=jahr, ebene="stadt",
                    segment=segment.key, objektart="etw", kennzahl="kauffaelle",
                    wert=segment.total_count, einheit="Verkäufe", seite=seite,
                    methode=methode,
                ))

    # Die Preisreihen hängen an der Stadt, nicht am Jahrgang: sie reichen
    # weiter zurück als die Gebietstabellen -- bei Wiesbaden bis 2007.
    for linie, punkte in (daten.verlauf or {}).items():
        for jahr, wert in punkte:
            raus.append(Faktum(
                quelle=daten.key, bericht=daten.report_year, jahr=jahr,
                ebene="verlauf", gebiet=linie, objektart="etw",
                kennzahl="preis", wert=wert, einheit="€/m²",
                methode="abgelesen" if daten.key == "wiesbaden" else "text",
            ))
    return raus


def dritte_fakten(broker: dict) -> list[Faktum]:
    """Die von Hand gepflegten Zahlen Dritter.

    Auch sie gehören in denselben Speicher -- getrennt gehalten wird über die
    Quelle und die Methode 'manuell', nicht über eine eigene Datei.
    """
    raus: list[Faktum] = []
    for eintrag in (broker or {}).get("eintraege", []):
        quelle = (eintrag.get("quelle") or "unbekannt").lower()
        objektart = "whgh" if "geschäftsh" in (eintrag.get("objektart") or "").lower() \
            else "etw"
        jahr = _jahr_aus(eintrag.get("stand", "")) or 0
        seite = eintrag.get("seite") or None
        for gebiet, wert in (eintrag.get("werte") or {}).items():
            paare = ([("min", wert[0]), ("max", wert[1])]
                     if isinstance(wert, (list, tuple)) and len(wert) == 2
                     else [("", wert)])
            for zusatz, einzel in paare:
                raus.append(Faktum(
                    quelle=quelle, bericht=jahr, jahr=jahr,
                    ebene=eintrag.get("ebene") or "stadt",
                    gebiet=gebiet, segment=eintrag.get("stadt") or "",
                    objektart=objektart,
                    kennzahl="preis" + (f"_{zusatz}" if zusatz else ""),
                    wert=einzel, einheit=eintrag.get("einheit") or "€/m²",
                    seite=int(seite) if str(seite).isdigit() else None,
                    methode="manuell",
                ))
    return raus


def _seitenzahl(text: str) -> int | None:
    import re
    treffer = re.search(r"S\.\s*(\d+)", text or "")
    return int(treffer.group(1)) if treffer else None


def _jahr_aus(text: str) -> int | None:
    import re
    treffer = re.search(r"(20\d{2})", text or "")
    return int(treffer.group(1)) if treffer else None


def lagere_ein(con: sqlite3.Connection, fakten: Iterable[Faktum]) -> int:
    return db.schreibe(con, fakten)


# ===========================================================================
# Auslesen: aus der Datenbank zurück in die Objekte, die die Ausgabe erwartet
# ===========================================================================
#
# Die Ausgabe wurde bewusst nicht angefasst. Sie bekommt dieselben Objekte wie
# vorher -- nur kommen die jetzt aus dem Speicher statt aus einem frisch
# geparsten PDF. Damit bleiben 1.300 Zeilen Darstellungscode unberührt.

def lade_hamburg(con: sqlite3.Connection, source, imb):
    """Baut den Hamburger Report aus der Datenbank."""
    report = imb.Report(
        source_key=source.key, city=source.city, publisher=source.publisher,
        area_label=source.area_label, landing_page=source.landing_page,
    )

    for jahr in db.jahre(con, source.key, "preis", "gebiet"):
        bericht = db.neuester_bericht(con, source.key, jahr, "gebiet")
        meta = db.bericht_meta(con, source.key, bericht)
        jahrgang = imb.YearData(
            report_year=bericht, data_year=jahr,
            pdf_url=source.url(bericht),
            pages=meta.get("pages", {}),
            headings=meta.get("headings", {}),
            ocr_tables=meta.get("ocrTables", {}),
        )

        for zeile in db.werte(con, source.key, jahr, ebene="gebiet", bericht=bericht):
            feld = jahrgang.areas.setdefault(zeile["gebiet"], imb.AreaValues())
            wert = zeile["wert"]
            paar = (zeile["objektart"], zeile["kennzahl"])
            if paar == ("etw", "preis"):
                feld.price = _ganz(wert); feld.price_marker = zeile["marker"]
            elif paar == ("etw", "kauffaelle"):
                feld.count = _ganz(wert); feld.count_marker = zeile["marker"]
            elif paar == ("etw", "faktor"):
                feld.factor = wert
            elif paar == ("mfh", "verkaeufe"):
                feld.mfh_count = _ganz(wert); feld.mfh_count_marker = zeile["marker"]
            elif paar == ("mfh", "faktor"):
                feld.mfh_factor = wert

        for zeile in db.werte(con, source.key, jahr, ebene="stadt", bericht=bericht):
            if zeile["kennzahl"] == "preis" and zeile["objektart"] == "etw":
                jahrgang.totals["preis"] = _ganz(zeile["wert"])
            elif zeile["kennzahl"] == "kauffaelle" and zeile["objektart"] == "etw":
                jahrgang.totals["kauffaelle"] = _ganz(zeile["wert"])

        for zeile in db.werte(con, source.key, jahr, ebene="baujahr_lage"):
            kennzahl = zeile["kennzahl"].capitalize()
            jahrgang.quality.setdefault(zeile["gebiet"], {}) \
                            .setdefault(kennzahl, {})[zeile["segment"]] = _ganz(zeile["wert"])

        report.years.append(jahrgang)

    # Die Matrix reicht ein Jahr weiter als die Stadtteiltabelle. Solche
    # Jahrgänge haben keine Gebietswerte und tauchen oben deshalb nicht auf.
    vorhanden = {j.data_year for j in report.years}
    for jahr in db.jahre(con, source.key, "mittelwert", "baujahr_lage"):
        if jahr in vorhanden:
            continue
        bericht = db.neuester_bericht(con, source.key, jahr, "baujahr_lage")
        jahrgang = imb.YearData(report_year=bericht, data_year=jahr,
                                pdf_url=source.url(bericht))
        for zeile in db.werte(con, source.key, jahr, ebene="baujahr_lage"):
            kennzahl = zeile["kennzahl"].capitalize()
            jahrgang.quality.setdefault(zeile["gebiet"], {}) \
                            .setdefault(kennzahl, {})[zeile["segment"]] = _ganz(zeile["wert"])
        if jahrgang.quality:
            report.years.append(jahrgang)
    report.years.sort(key=lambda j: j.data_year)

    for objektart, ziel in (("etw", "index_series"), ("mfh", "index_series_mfh")):
        reihe = [(int(r["jahr"]), _ganz(r["wert"])) for r in con.execute(
            "SELECT jahr, wert FROM fakten WHERE quelle=? AND ebene='stadt' "
            "AND kennzahl='index' AND objektart=? ORDER BY jahr",
            (source.key, objektart))]
        setattr(report, ziel, reihe)

    standard: dict[int, dict] = {}
    for r in con.execute(
            "SELECT jahr, segment, kennzahl, wert FROM fakten WHERE quelle=? "
            "AND kennzahl LIKE 'standardwohnung%' ORDER BY jahr", (source.key,)):
        zusatz = r["kennzahl"].partition("_")[2]
        feld = r["segment"] + (f"_{zusatz}" if zusatz else "")
        standard.setdefault(int(r["jahr"]), {"year": int(r["jahr"])})[feld] = _ganz(r["wert"])
    # Feldreihenfolge wie beim Leser, damit die Ausgabe Zeichen fuer Zeichen passt.
    ordnung = ("year", "altbau", "neubau", "altbau_sqm", "neubau_sqm")
    report.standard_flat = [
        {k: standard[j][k] for k in ordnung if k in standard[j]}
        for j in sorted(standard)
    ]

    return report


def lade_stadt(con: sqlite3.Connection, quelle: str, staedte):
    """Baut eine Zusatzstadt aus der Datenbank."""
    jahrgaenge_vorhanden = db.jahre(con, quelle, "preis", "gebiet")
    if not jahrgaenge_vorhanden:
        return None

    neuestes = jahrgaenge_vorhanden[-1]
    meta = db.bericht_meta(con, quelle, db.neuester_bericht(con, quelle, neuestes))
    stadt = meta.get("stadt", {})
    # Die Stadtangaben stehen im Beiwerk des neuesten Berichts.
    label = stadt.get("segmente", {})

    jahre_objekte = []
    for jahr in jahrgaenge_vorhanden:
        bericht = db.neuester_bericht(con, quelle, jahr)
        segmente: dict[str, staedte.Segment] = {}
        for zeile in db.werte(con, quelle, jahr, ebene="gebiet", bericht=bericht):
            key = zeile["segment"]
            seg = segmente.get(key)
            if seg is None:
                beschreibung = label.get(key, {})
                seg = staedte.Segment(
                    key=key, label=beschreibung.get("label", key.capitalize()),
                    unit=beschreibung.get("unit", "€/m²"),
                    note=beschreibung.get("note", ""))
                segmente[key] = seg
            feld = seg.areas.setdefault(zeile["gebiet"], {"p": None, "c": None, "m": None})
            if zeile["kennzahl"] == "preis":
                feld["p"] = _ganz(zeile["wert"]); feld["m"] = zeile["marker"]
            elif zeile["kennzahl"] == "kauffaelle":
                feld["c"] = _ganz(zeile["wert"])
            elif zeile["kennzahl"] in ("baujahr", "wohnflaeche"):
                feld[zeile["kennzahl"]] = _ganz(zeile["wert"])

        for zeile in db.werte(con, quelle, jahr, ebene="stadt", bericht=bericht):
            seg = segmente.get(zeile["segment"])
            if seg is None:
                continue
            if zeile["kennzahl"] == "preis":
                seg.total = _ganz(zeile["wert"])
            elif zeile["kennzahl"] == "kauffaelle":
                seg.total_count = _ganz(zeile["wert"])

        # Reihenfolge wie im Leser, nicht wie sie die Datenbank ausspuckt.
        sortiert = [segmente[k] for k in label if k in segmente] \
            + [s for k, s in segmente.items() if k not in label]
        jahr_meta = db.bericht_meta(con, quelle, bericht)
        jahre_objekte.append(staedte.CityYear(
            data_year=jahr, report_year=bericht,
            source_page=jahr_meta.get("stadt", {}).get("sourcePage", ""),
            segments=sortiert))

    # Reihenfolge der Linien wie im Leser -- die Datenbank sortiert anders.
    verlauf: dict[str, list[tuple[int, int]]] = {}
    for r in con.execute(
            "SELECT gebiet, jahr, wert FROM fakten WHERE quelle=? AND ebene='verlauf' "
            "ORDER BY jahr", (quelle,)):
        verlauf.setdefault(r["gebiet"], []).append((int(r["jahr"]), _ganz(r["wert"])))
    ordnung = stadt.get("verlaufLinien") or sorted(verlauf)
    verlauf = {k: verlauf[k] for k in ordnung if k in verlauf}

    neueste = jahre_objekte[-1]
    return staedte.CityDataset(
        key=quelle, city=stadt.get("city", quelle.capitalize()),
        area_label=stadt.get("areaLabel", "Gebiet"),
        publisher=stadt.get("publisher", ""),
        report_year=neueste.report_year, data_year=neueste.data_year,
        pdf_url=stadt.get("pdfUrl", ""), source_page=neueste.source_page,
        segments=neueste.segments, notes=stadt.get("notes", []),
        years=jahre_objekte if len(jahre_objekte) > 1 else [],
        verlauf=verlauf,
        verlauf_titel=stadt.get("verlaufTitel", ""),
        verlauf_note=stadt.get("verlaufNote", ""),
    )


def stadt_meta(daten) -> dict:
    """Was sich nicht als Faktum ausdrücken lässt: Namen, Beschriftungen, Hinweise."""
    segmente = {}
    for jahrgang in (daten.years or []):
        for seg in jahrgang.segments:
            segmente.setdefault(seg.key, {"label": seg.label, "note": seg.note,
                                          "unit": seg.unit})
    for seg in daten.segments:
        segmente.setdefault(seg.key, {"label": seg.label, "note": seg.note,
                                      "unit": seg.unit})
    return {
        "city": daten.city, "areaLabel": daten.area_label,
        "publisher": daten.publisher, "pdfUrl": daten.pdf_url,
        "sourcePage": daten.source_page, "notes": daten.notes,
        "segmente": segmente,
        "verlaufTitel": daten.verlauf_titel,
        "verlaufNote": daten.verlauf_note,
        "verlaufLinien": list((daten.verlauf or {}).keys()),
    }


def _ganz(wert):
    """SQLite gibt REAL zurück; die Berichte führen ganze Zahlen.

    Der Stadtteilfaktor ist die Ausnahme -- er hat Nachkommastellen und darf
    nicht gerundet werden.
    """
    if wert is None:
        return None
    return int(wert) if float(wert).is_integer() else wert
