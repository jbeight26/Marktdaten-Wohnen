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

import pdfplumber

from imb import (
    BROWSER_HEADERS, DownloadError, ExtractionError,
    _group_rows, cache_hit, download_pdf,
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
class CityDataset:
    key: str
    city: str
    area_label: str
    publisher: str
    report_year: int
    data_year: int
    pdf_url: str
    source_page: str = ""
    segments: list[Segment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


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
