#!/usr/bin/env python3
"""
Weitere Städte: Wiesbaden und Kiel.

Die Berichte dieser Gutachterausschüsse sind strukturell anders aufgebaut als
der Hamburger. Deshalb bekommt jede Stadt einen eigenen Tabellenleser; gemeinsam
ist nur das Ausgabeformat (CityDataset), das die HTML-Ansicht erwartet.

Was wo steht:

  Wiesbaden  Stadtbezirk x Baujahr x Wohnfläche, Zelle "Anzahl/Mittelpreis",
             getrennt nach Neubau, Umwandlung und Weiterverkauf.
  Kiel       Stadtteil -> Kauffälle, Ø Baujahr, Ø Wohnfläche, Ø Kaufpreis,
             nur für Weiterverkäufe. Neubau und Umwandlung nur gesamtstädtisch.
"""

from __future__ import annotations

import collections
import io
import re
from dataclasses import dataclass, field
from typing import Sequence

import pdfplumber

from imb import (
    BROWSER_HEADERS, DownloadError, ExtractionError,
    _group_rows, cache_hit, download_pdf, is_pdf,
)


# ===========================================================================
# Gemeinsames Ausgabeformat
# ===========================================================================

@dataclass
class Segment:
    """Eine Bar-Chart-fähige Sicht: Gebiet -> Wert."""

    key: str
    label: str
    unit: str
    areas: dict[str, dict] = field(default_factory=dict)
    total: int | None = None
    total_count: int | None = None
    note: str = ""
    # Optional: feinere Aufschlüsselung, z. B. Baujahr x Wohnfläche
    matrix: dict = field(default_factory=dict)
    matrix_columns: list[str] = field(default_factory=list)


@dataclass
class CityYear:
    """Ein Preisjahr einer Zusatzstadt.

    Wiesbaden und Kiel fuehren genau einen; Frankfurt fuenf, weil jeder Bericht
    zwei Jahrgaenge nebeneinanderstellt.
    """

    data_year: int
    report_year: int
    source_page: str = ""
    segments: list[Segment] = field(default_factory=list)


@dataclass
class CityDataset:
    key: str
    city: str
    area_label: str
    publisher: str
    report_year: int
    data_year: int
    pdf_url: str
    source_page: str = ""
    # Das neueste Jahr -- die Ansicht startet hier, und aeltere Leser, die
    # keine Jahrgaenge kennen, kommen damit unveraendert zurecht.
    segments: list[Segment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Alle Preisjahre, aeltestes zuerst. Leer bei einjaehrigen Staedten.
    years: list[CityYear] = field(default_factory=list)


# ===========================================================================
# Wiesbaden
# ===========================================================================

WI_CELL = re.compile(r"^(\d+)/([\d.]+|\*)$")
WI_EMPTY = {"–", "-", "—"}
WI_TOTAL = re.compile(r"^(Wi-?\s?Gesamt|Gesamt)$", re.I)
WI_URL = "https://www.wiesbaden.de/vv/medien/merk/66/Immobilienmarktbericht-{year}.pdf"

# Der Bericht setzt die Überschriften mit Trennfehlern ("M ittelpreise"), deshalb
# wird nur auf den unverwechselbaren hinteren Teil gesucht.
WI_SEGMENTS = (
    ("neubau", "Neubau (Erstverkauf)", r"neugebauter\s+Eigentumswohnungen"),
    ("umwandlung", "Umwandlung aus Miete", r"in\s+Wohnungseigentum\s+umgewandelten\s+Mietwohnungen"),
    ("weiterverkauf", "Weiterverkauf (Bestand)", r"Wohnungseigentum\s+bei\s+Wiederverkäufen"),
)


def _wi_columns(words: list[dict]) -> list[tuple[float, float]]:
    cells = [w for w in words if WI_CELL.match(w["text"]) or w["text"] in WI_EMPTY]
    if len(cells) < 12:
        return []
    edges = sorted(w["x1"] for w in cells)
    clusters: list[list[float]] = [[edges[0]]]
    for edge in edges[1:]:
        if edge - clusters[-1][-1] > 12:
            clusters.append([])
        clusters[-1].append(edge)
    return [(min(c) - 9, max(c) + 3) for c in clusters if len(c) >= 5]


def _wi_headers(page) -> list[str]:
    """Baujahrsklassen der Seite, in Lesereihenfolge; Neubau hat keine."""
    text = page.extract_text() or ""
    found = re.findall(r"Baujahr\s+(bis\s+\d{4}|\d{4}\s*-\s*\d{4}|ab\s+\d{4})", text)
    return [re.sub(r"\s+", " ", f) for f in found]


def _wi_parse_page(page) -> tuple[dict, dict | None, list[str]]:
    words = [w for w in page.extract_words() if w["x0"] >= 0]
    columns = _wi_columns(words)
    if not columns:
        return {}, None, []

    rows = _group_rows(words, tolerance=5.0)
    areas: dict[str, dict[int, tuple[int, int | None]]] = {}
    total: dict[int, tuple[int, int | None]] | None = None

    for row in rows:
        names = [w["text"] for w in row
                 if w["x0"] < 110 and not WI_CELL.match(w["text"]) and w["text"] not in WI_EMPTY]
        name = " ".join(names).strip()
        if not name or any(c.isdigit() for c in name):
            continue

        values: dict[int, tuple[int, int | None]] = {}
        for word in row:
            if word["x0"] < 110:
                continue
            match = WI_CELL.match(word["text"])
            if not (match or word["text"] in WI_EMPTY):
                continue
            for i, (lo, hi) in enumerate(columns):
                if lo <= word["x1"] <= hi:
                    if match:
                        price = None if match.group(2) == "*" else int(match.group(2).replace(".", ""))
                        values[i] = (int(match.group(1)), price)
                    else:
                        values[i] = (0, None)
                    break
        if not values:
            continue
        if WI_TOTAL.match(name):
            total = values
        else:
            areas[name] = values

    return areas, total, _wi_headers(page)


def _wi_find_segment(pdf, pattern: str) -> list[int]:
    """Alle Seiten eines Segments, inklusive Tabellenfortsetzungen."""
    regex = re.compile(pattern, re.I)
    start = None
    for i, page in enumerate(pdf.pages):
        text = (page.extract_text() or "").replace("\n", " ")
        if not regex.search(text):
            continue
        # Das Inhaltsverzeichnis nennt dieselben Überschriften. Nur eine Seite,
        # die auch Tabellenzellen führt, ist der gesuchte Abschnitt.
        words = [w for w in page.extract_words() if w["x0"] >= 0]
        if _wi_columns(words):
            start = i
            break
    if start is None:
        return []

    # Fortsetzungsseiten wiederholen die Überschrift -- solange sie passt, gehört
    # die Seite zum Segment.
    pages = [start]
    for i in range(start + 1, len(pdf.pages)):
        text = (pdf.pages[i].extract_text() or "").replace("\n", " ")
        if not regex.search(text):
            break
        pages.append(i)
    return pages


def extract_wiesbaden(pdf_path, report_year: int) -> CityDataset:
    buffer = io.BytesIO(pdf_path.read_bytes())
    data = CityDataset(
        key="wiesbaden",
        city="Wiesbaden",
        area_label="Stadtbezirk",
        publisher="Gutachterausschuss für Immobilienwerte Wiesbaden",
        report_year=report_year,
        data_year=report_year - 1,
        pdf_url=WI_URL.format(year=report_year),
        source_page="https://www.wiesbaden.de/vv/produkte/66/wissenswertes",
    )

    with pdfplumber.open(buffer) as pdf:
        for key, label, pattern in WI_SEGMENTS:
            pages = _wi_find_segment(pdf, pattern)
            if not pages:
                data.notes.append(f"{label}: Abschnitt nicht gefunden")
                continue

            merged: dict[str, list[tuple[int, int | None]]] = collections.defaultdict(list)
            total_cells: list[tuple[int, int | None]] = []
            columns: list[str] = []

            for index in pages:
                page = pdf.pages[index]
                areas, total, headers = _wi_parse_page(page)
                page.close()
                if not areas:
                    continue
                spalten = len(next(iter(areas.values()), {})) or 4
                gruppen = headers or ["alle Baujahre"]
                pro = max(1, spalten // max(1, len(gruppen)))
                for i, g in enumerate(gruppen):
                    for j in range(pro):
                        columns.append(f"{g} · {['≤ 44','45–79','80–119','≥ 120'][j % 4]} m²")
                for name, values in areas.items():
                    for i in sorted(values):
                        merged[name].append(values[i])
                if total:
                    total_cells.extend(total[i] for i in sorted(total))

            if not merged:
                data.notes.append(f"{label}: keine Datensätze lesbar")
                continue

            segment = Segment(key=key, label=label, unit="€/m²",
                              matrix_columns=columns)
            for name, cells in merged.items():
                faelle = sum(n for n, _ in cells)
                gewicht = sum(n for n, p in cells if p is not None)
                mittel = (sum(n * p for n, p in cells if p is not None) / gewicht) if gewicht else None
                segment.areas[name] = {
                    "p": round(mittel) if mittel else None,
                    "c": faelle or None,
                    "m": None if mittel else ("*" if faelle else "-"),
                }
                segment.matrix[name] = [
                    {"c": n, "p": p} for n, p in cells
                ]
            segment.total_count = sum(n for n, _ in total_cells) or None
            gew = sum(n for n, p in total_cells if p is not None)
            if gew:
                segment.total = round(sum(n * p for n, p in total_cells if p is not None) / gew)
            segment.note = (
                "Mittelwert je Stadtbezirk aus den ausgewiesenen Zellen, gewichtet "
                "nach Kauffällen. Zellen mit weniger als drei Fällen weist der "
                "Bericht ohne Preis aus und bleiben deshalb außen vor."
            )
            data.segments.append(segment)

    if not data.segments:
        raise ExtractionError("Wiesbaden: keine Segmente auswertbar.")
    return data


# ===========================================================================
# Kiel
# ===========================================================================
#
# Kiel führt Stadtteilwerte nur für Weiterverkäufe. Neubau und Umwandlung
# stehen ausschließlich gesamtstädtisch als Jahresreihe.

KI_NR = re.compile(r"^\((\d+)\)$")
KI_NUM = re.compile(r"^\d{1,3}(?:\.\d{3})*$|^\d+$")
KI_NAME_X = (130, 290)
KI_STOP = re.compile(r"^\*|Immobilienmarktbericht")
KI_HEADING = r"Kaufpreise\s*\(KP\)\s*je\s*m²\s*Wohnfläche.{0,20}nach\s+Stadtteilen"
KI_INDEX = "https://www.gutachterausschuss-kiel.de/dienstleistungen/marktbericht-marktinformationen/"


def _ki_name_fragment(row: list[dict]) -> str:
    if any(KI_NR.match(w["text"]) for w in row):
        return ""
    if any(KI_NUM.match(w["text"]) and w["x0"] > 280 for w in row):
        return ""
    text = " ".join(w["text"] for w in row
                    if KI_NAME_X[0] <= w["x0"] <= KI_NAME_X[1])
    return "" if KI_STOP.search(text) else text.strip()


def _ki_parse_districts(page) -> dict[str, dict]:
    """Liest die Stadtteiltabelle: Nummer, Name, Fälle, Ø Baujahr, Ø WF, Ø Preis.

    Namen können umbrechen (Neumühlen-Dietrichsdorf steht auf drei Zeilen), die
    Zeile mit der Nummer bleibt dann ohne Namen. Deshalb werden die Nachbarzeilen
    mit ausgewertet.
    """
    words = [w for w in page.extract_words() if w["x0"] >= 0]
    rows = _group_rows(words, tolerance=5.0)

    edges = sorted(w["x1"] for w in words if KI_NUM.match(w["text"]) and w["x0"] > 280)
    if not edges:
        return {}
    clusters: list[list[float]] = [[edges[0]]]
    for edge in edges[1:]:
        if edge - clusters[-1][-1] > 14:
            clusters.append([])
        clusters[-1].append(edge)
    columns = [(min(c) - 12, max(c) + 3) for c in clusters if len(c) >= 8]
    if len(columns) < 4:
        return {}

    out: dict[str, dict] = {}
    for i, row in enumerate(rows):
        marker = next((w for w in row if KI_NR.match(w["text"])), None)
        if not marker:
            continue
        name = " ".join(w["text"] for w in row
                        if KI_NAME_X[0] <= w["x0"] <= KI_NAME_X[1]
                        and not KI_NUM.match(w["text"])).strip()
        if not name:
            above = _ki_name_fragment(rows[i - 1]) if i else ""
            below = _ki_name_fragment(rows[i + 1]) if i + 1 < len(rows) else ""
            name = (above + below) if above.endswith("-") else f"{above} {below}".strip()
        name = name.strip(" <-")
        if not name:
            continue

        values: dict[int, int] = {}
        for word in row:
            if not KI_NUM.match(word["text"]):
                continue
            for j, (lo, hi) in enumerate(columns):
                if lo <= word["x1"] <= hi:
                    values[j] = int(word["text"].replace(".", ""))
                    break

        if len(values) >= 4:
            out[name] = {"p": values[3], "c": values[0], "m": None,
                         "baujahr": values[1], "wohnflaeche": values[2]}
        else:
            out[name] = {"p": None, "c": None, "m": "*",
                         "baujahr": None, "wohnflaeche": None}
    return out


def extract_kiel(pdf_path, report_year: int, pdf_url: str = "") -> CityDataset:
    buffer = io.BytesIO(pdf_path.read_bytes())
    data = CityDataset(
        key="kiel",
        city="Kiel",
        area_label="Stadtteil",
        publisher="Gutachterausschuss für Grundstückswerte in der Landeshauptstadt Kiel",
        report_year=report_year,
        data_year=report_year - 1,
        pdf_url=pdf_url,
        source_page=KI_INDEX,
    )

    regex = re.compile(KI_HEADING, re.I)
    with pdfplumber.open(buffer) as pdf:
        target = None
        for i, page in enumerate(pdf.pages):
            text = (page.extract_text() or "").replace("\n", " ")
            page.close()
            if regex.search(text):
                target = i
                break
        if target is None:
            raise ExtractionError("Kiel: Stadtteiltabelle nicht gefunden.")

        districts = _ki_parse_districts(pdf.pages[target])
        pdf.pages[target].close()

    if not districts:
        raise ExtractionError("Kiel: Stadtteiltabelle nicht lesbar.")

    priced = {k: v for k, v in districts.items() if v["p"] is not None}
    faelle = sum(v["c"] for v in priced.values())
    mittel = round(sum(v["c"] * v["p"] for v in priced.values()) / faelle) if faelle else None

    segment = Segment(
        key="weiterverkauf",
        label="Weiterverkauf (Bestand)",
        unit="€/m²",
        areas=districts,
        total=mittel,
        total_count=faelle,
        note=("Der Bericht führt Stadtteilwerte nur für Weiterverkäufe. Neubau und "
              "Umwandlung stehen dort ausschließlich gesamtstädtisch. Der "
              "Gesamtwert ist aus den Stadtteilen gewichtet gerechnet, nicht "
              "vom Gutachterausschuss ausgewiesen."),
    )
    data.segments.append(segment)
    data.notes.append(
        "Kiel weist je Stadtteil zusätzlich das mittlere Baujahr und die mittlere "
        "Wohnfläche aus; beides steht im Tooltip."
    )
    return data


# ===========================================================================
# Beschaffung
# ===========================================================================

def fetch_wiesbaden(cache_dir, year: int, refresh: bool = False):
    target = cache_dir / f"WI{year}.pdf"
    if cache_hit(target, refresh):
        return target
    return download_pdf(WI_URL.format(year=year), target)


def discover_kiel(session_get) -> dict[int, str]:
    """Kiel hat keine Jahres-URL: die Adressen stehen auf der Übersichtsseite."""
    html = session_get(KI_INDEX)
    links = re.findall(r'href="([^"]*?Immobilienmarktbericht[^"]*?\.pdf)"', html, re.I)
    out: dict[int, str] = {}
    for link in links:
        match = re.search(r"(20\d{2})", link.rsplit("/", 1)[-1])
        if match:
            out[int(match.group(1))] = link
    return out


def fetch_kiel(cache_dir, year: int, url: str, refresh: bool = False):
    target = cache_dir / f"KI{year}.pdf"
    if cache_hit(target, refresh):
        return target
    return download_pdf(url, target)


# ===========================================================================
# Frankfurt am Main
# ===========================================================================
#
# Frankfurt kommt NICHT aus dem Netz: die Stadt schuetzt ihre Downloads mit
# einer Cloudflare-Pruefung, und Bot-Schutz wird nicht umgangen. Die Berichte
# muessen von Hand in den Zwischenspeicher gelegt werden, als FFM<Jahr>.pdf.
#
# Aufbau der Leittabelle (Abschnitt 3.7.3): 15 Gruppen von Grundbuchbezirken,
# je Gruppe zwei Jahrgaenge, je Jahrgang sechs Baujahrsklassen mit Anzahl und
# Preis. Anders als in Hamburg steht der Gebietsname in Klammern hinter den
# Bezirksnummern -- und faellt bei langen Namen in die naechste Zeile.

FR_HEADING = re.compile(
    r"Mittlere\s+Preise\s+für\s+Eigentumswohnungen\s+nach\s+Grundbuchbezirken")
FR_ZEILE = re.compile(r"^(20\d{2})\s+(.+)$")
FR_GRUPPE = re.compile(r"^Grundbuchbezirke?\s+(.+)$")
FR_KLAMMER = re.compile(r"\(([^)]*)\)")
FR_FEHLT = {"-", "–", "—", "..", "."}

# Reihenfolge wie im Bericht. "Neubau" ist die letzte Spalte und wird getrennt
# ausgewiesen -- die vorletzte heisst ausdruecklich "ab 1991 o. Neubauten".
FR_KLASSEN = ("bis 1918", "1919–1949", "1950–1977", "1978–1990",
              "ab 1991 ohne Neubau", "Neubau")
FR_BESTAND = FR_KLASSEN[:-1]


def _fr_zahl(text: str) -> int | None:
    if text in FR_FEHLT:
        return None
    try:
        return int(text.replace(".", ""))
    except ValueError:
        return None


def _fr_seite(pdf) -> int:
    """Die Seite mit den meisten Datenzeilen gewinnt.

    Der Bericht nennt die Ueberschrift auch im Inhaltsverzeichnis, und der
    Jahrgang 2023 fuehrt zusaetzlich einen Abschnitt 3.7.3.1 ohne Zahlen.
    """
    beste, punkte = -1, 0
    for i, page in enumerate(pdf.pages):
        text = page.extract_text() or ""
        if not FR_HEADING.search(text):
            continue
        treffer = sum(1 for z in text.splitlines() if FR_ZEILE.match(z.strip()))
        if treffer > punkte:
            beste, punkte = i, treffer
    if beste < 0 or punkte == 0:
        raise ExtractionError(
            "Tabelle 3.7.3 (Preise nach Grundbuchbezirken) nicht gefunden")
    return beste


def _fr_parse(page) -> dict[int, dict[str, list[tuple[int | None, int | None]]]]:
    """Liefert {Jahr: {Gebiet: [(Anzahl, Preis) je Baujahrsklasse]}}."""
    zeilen = [z.strip() for z in (page.extract_text() or "").splitlines()]
    daten: dict[int, dict[str, list]] = {}
    gebiet = None

    for i, zeile in enumerate(zeilen):
        gruppe = FR_GRUPPE.match(zeile)
        if gruppe:
            klammer = FR_KLAMMER.search(zeile)
            if not klammer and i + 1 < len(zeilen):
                # Langer Name -- er steht allein in der Folgezeile.
                klammer = FR_KLAMMER.search(zeilen[i + 1])
            if klammer:
                gebiet = re.sub(r"\s*,\s*", ", ", klammer.group(1).strip())
            continue

        werte = FR_ZEILE.match(zeile)
        if not werte or gebiet is None:
            continue
        teile = werte.group(2).split()
        if len(teile) != 2 * len(FR_KLASSEN):
            continue
        paare = [(_fr_zahl(teile[k]), _fr_zahl(teile[k + 1]))
                 for k in range(0, len(teile), 2)]
        daten.setdefault(int(werte.group(1)), {})[gebiet] = paare

    if not daten:
        raise ExtractionError("Keine Datenzeilen in der Frankfurter Leittabelle")
    return daten


def _fr_segment(key: str, label: str, spalten: Sequence[int],
                gebiete: dict[str, list], note: str = "") -> Segment:
    """Fasst die gewaehlten Baujahrsspalten je Gebiet zusammen.

    Gewichtet wird nach Kauffaellen -- ein Mittel aus 3 und aus 122 Verkaeufen
    darf nicht gleich schwer wiegen.
    """
    seg = Segment(key=key, label=label, unit="€/m²", note=note)
    summe = anzahl_gesamt = 0
    for name, paare in gebiete.items():
        gewicht = wert = 0
        for spalte in spalten:
            anz, preis = paare[spalte]
            if anz and preis:
                gewicht += anz
                wert += anz * preis
        if gewicht:
            mittel = round(wert / gewicht)
            seg.areas[name] = {"p": mittel, "c": gewicht, "m": None}
            summe += wert
            anzahl_gesamt += gewicht
        else:
            seg.areas[name] = {"p": None, "c": None, "m": "*"}
    if anzahl_gesamt:
        seg.total = round(summe / anzahl_gesamt)
        seg.total_count = anzahl_gesamt
    return seg


def _fr_jahrgang(gebiete: dict[str, list], jahr: int, report_year: int,
                 seite: int) -> CityYear:
    bestand = list(range(len(FR_BESTAND)))
    return CityYear(
        data_year=jahr,
        report_year=report_year,
        source_page=f"S. {seite}, Abschnitt 3.7.3",
        segments=[
            _fr_segment("bestand", "Bestand (ohne Neubau)", bestand, gebiete,
                        note="Über alle Baujahrsklassen außer Neubau, nach "
                             "Kauffällen gewichtet."),
            _fr_segment("neubau", "Neubau", [len(FR_KLASSEN) - 1], gebiete),
            _fr_segment("altbau", "Altbau (bis 1918)", [0], gebiete),
        ],
    )


def extract_frankfurt(cache_dir) -> CityDataset:
    """Liest alle abgelegten Frankfurter Berichte zu einer Stadt zusammen.

    Jeder Bericht fuehrt zwei Preisjahre, aufeinanderfolgende Berichte
    ueberschneiden sich also um eines. Bei Ueberschneidung gewinnt der neuere
    Bericht -- er enthaelt die spaeter korrigierten Zahlen.
    """
    berichte = find_frankfurt(cache_dir)
    if not berichte:
        raise DownloadError(
            f"kein Bericht abgelegt — FFM<Jahr>.pdf nach {cache_dir} legen")

    jahrgaenge: dict[int, CityYear] = {}
    for report_year in sorted(berichte):              # alt zuerst, neu gewinnt
        try:
            with pdfplumber.open(io.BytesIO(berichte[report_year].read_bytes())) as pdf:
                seite = _fr_seite(pdf)
                daten = _fr_parse(pdf.pages[seite])
        except (ExtractionError, OSError) as exc:
            print(f"(Bericht {report_year} übersprungen: {exc}) ", end="", flush=True)
            continue
        for jahr, gebiete in daten.items():
            jahrgaenge[jahr] = _fr_jahrgang(gebiete, jahr, report_year, seite + 1)

    if not jahrgaenge:
        raise ExtractionError("kein Jahrgang auswertbar")

    reihe = [jahrgaenge[j] for j in sorted(jahrgaenge)]
    neueste = reihe[-1]
    return CityDataset(
        key="frankfurt",
        city="Frankfurt am Main",
        area_label="Grundbuchbezirk",
        publisher="Gutachterausschuss für Immobilienwerte Frankfurt am Main",
        report_year=neueste.report_year,
        data_year=neueste.data_year,
        pdf_url="",
        source_page=neueste.source_page,
        segments=neueste.segments,
        years=reihe,
        notes=[
            "Frankfurt gliedert nach Grundbuchbezirken, nicht nach Stadtteilen; "
            "die Namen in Klammern sind die Ortsteile darin.",
            "Die Gebietswerte sind aus den Baujahrszellen nach Kauffällen "
            "gewichtet gerechnet, nicht im Bericht abgelesen.",
            "Der Bericht wird von Hand bereitgestellt — die Stadt sperrt "
            "automatisierte Downloads.",
        ],
    )


def find_frankfurt(cache_dir) -> dict[int, "Path"]:
    """Von Hand abgelegte Frankfurter Berichte im Zwischenspeicher.

    Erwartet FFM<Jahr>.pdf. Nicht-PDFs werden uebergangen: unter genau diesem
    Namen ist schon einmal eine Cloudflare-Sperrseite gelandet.
    """
    treffer: dict[int, "Path"] = {}
    for pfad in sorted(cache_dir.glob("FFM*.pdf")):
        jahr = re.search(r"(20\d{2})", pfad.name)
        if jahr and is_pdf(pfad):
            treffer[int(jahr.group(1))] = pfad
    return treffer
