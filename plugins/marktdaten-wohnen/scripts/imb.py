#!/usr/bin/env python3
"""
Eigentumswohnungspreise aus den Immobilienmarktberichten des Gutachterausschusses.

Lädt alle verfügbaren Jahrgänge, extrahiert je Jahrgang zwei Stadtteil-Tabellen
(mittlere Kaufpreise je m² Wohnfläche und Anzahl der Kauffälle) und rendert das
Ergebnis als eine eigenständige HTML-Datei mit Jahres- und Verlaufsansicht.

Kein KI-Anteil: Download, Tabellenerkennung und Ausgabe sind deterministisch.
Derselbe Bericht liefert immer dieselben Zahlen.

Beispiele
---------
    python imb.py                                # alle verfügbaren Jahrgänge
    python imb.py --years 2024-2025
    python imb.py --year 2022 --pdf ./IMB2022.pdf
    python imb.py --serve                        # mit funktionsfähigem Abfrage-Button
    python imb.py --list-sources
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import html
import io
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    sys.exit("Fehlt: pdfplumber. Installieren mit:  pip install -r requirements.txt")

try:
    import requests
except ImportError:  # pragma: no cover
    sys.exit("Fehlt: requests. Installieren mit:  pip install -r requirements.txt")


# ===========================================================================
# Konfiguration: Quellen und Tabellen
# ===========================================================================

@dataclass(frozen=True)
class Table:
    """Eine Stadtteil-Tabelle innerhalb eines Berichts.

    Die Geometrie ist bei allen diesen Tabellen gleich (Name links, Wert
    rechtsbündig, mehrere Spaltenpaare nebeneinander). Unterschiedlich sind nur
    Überschrift und der plausible Wertebereich.
    """

    key: str
    label: str
    unit: str
    heading_re: str
    aggregate_re: str
    min_value: float
    max_value: float
    page_hint: int                      # Startpunkt der Seitensuche
    marker_meanings: dict[str, str]
    decimal: bool = False               # Werte mit Dezimalkomma (z. B. 1,027)


PRICE_TABLE = Table(
    key="preis",
    label="Mittlerer Kaufpreis",
    unit="€/m²",
    heading_re=r"Kaufpreise.{0,60}Wohnfläche.{0,20}von\s+Eigentumswohnungen",
    aggregate_re=r"^Hamburg\s+gesamt$",
    min_value=300,
    max_value=100_000,
    page_hint=44,
    marker_meanings={
        "*": "weniger als 3 Kauffälle",
        "-": "kein Wert ausgewiesen",
    },
)

SALES_TABLE = Table(
    key="kauffaelle",
    label="Kauffälle",
    unit="Verkäufe",
    heading_re=r"Verteilung\s+der\s+Verkäufe\s+von\s+Eigentumswohnungen",
    aggregate_re=r"^Hamburg\s+gesamt$",
    min_value=1,
    max_value=100_000,
    page_hint=40,
    marker_meanings={
        "*": "keine Angabe",
        "-": "keine Verkäufe",
    },
)


FACTOR_TABLE = Table(
    key="faktor",
    label="Stadtteilfaktor",
    unit="Faktor",
    heading_re=r"Stadtteilfaktor\s+für\s+den\s+Gebäudefaktor\s+für\s+Eigentumswohnungen",
    aggregate_re=r"^$",                 # diese Tabelle hat keinen Gesamtwert
    min_value=0.3,
    max_value=3.0,
    page_hint=175,
    marker_meanings={"*": "keine Angabe", "-": "kein Wert ausgewiesen"},
    decimal=True,
)


SALES_MFH_TABLE = Table(
    key="mfh_verkaeufe",
    label="Verkäufe Mehrfamilienhäuser",
    unit="Verkäufe",
    heading_re=r"Verteilung\s+der\s+Verkäufe\s+von\s+Mehrfamilienhäusern",
    aggregate_re=r"^Hamburg\s+gesamt$",
    min_value=1,
    max_value=100_000,
    page_hint=26,
    marker_meanings={"*": "keine Angabe", "-": "keine Verkäufe"},
)

FACTOR_MFH_TABLE = Table(
    key="mfh_faktor",
    label="Stadtteilfaktor Mehrfamilienhäuser",
    unit="Faktor",
    heading_re=r"Stadtteilfaktor\s+für\s+den\s+Gebäudefaktor\s+für\s+Mehrfamilienhäusern?",
    aggregate_re=r"^$",
    min_value=0.3,
    max_value=3.0,
    page_hint=134,
    marker_meanings={"*": "keine Angabe", "-": "kein Wert ausgewiesen"},
    decimal=True,
)


@dataclass(frozen=True)
class Source:
    """Eine Stadt und ihre Berichtsreihe.

    Eine weitere Stadt ergänzt man allein hier -- der Parser ist nicht
    stadtspezifisch.
    """

    key: str
    city: str
    publisher: str
    url_template: str
    filename_template: str
    area_label: str
    tables: tuple[Table, ...]
    landing_page: str = ""
    earliest_year: int = 2022          # Untergrenze der Jahrgangssuche

    def url(self, year: int) -> str:
        return self.url_template.format(year=year)

    def filename(self, year: int) -> str:
        return self.filename_template.format(year=year)

    def table(self, key: str) -> Table:
        for t in self.tables:
            if t.key == key:
                return t
        raise KeyError(key)


SOURCES: dict[str, Source] = {
    "hamburg": Source(
        key="hamburg",
        city="Hamburg",
        publisher="Gutachterausschuss für Grundstückswerte in Hamburg",
        url_template="https://daten-hamburg.de/opendata/immobilienmarktberichte/IMB{year}.pdf",
        filename_template="IMB{year}.pdf",
        landing_page="https://www.hamburg.de/politik-und-verwaltung/behoerden/bsw/themen/geoinformation-vermessung/gutachterausschuss/immobilienmarktbericht",
        area_label="Stadtteil",
        tables=(PRICE_TABLE, SALES_TABLE, FACTOR_TABLE,
                SALES_MFH_TABLE, FACTOR_MFH_TABLE),
        earliest_year=2022,
    ),
}

# Bewusst ausserhalb des Arbeitsverzeichnisses: die Berichte sind 10-30 MB gross,
# und auf Cloud-Laufwerken (Google Drive, OneDrive) bremst der wahlfreie Zugriff
# beim Parsen dramatisch -- Minuten statt Sekunden.
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "immobilienmarktberichte"


# ===========================================================================
# Datenmodell
# ===========================================================================

@dataclass
class AreaValues:
    """Werte eines Stadtteils in einem Jahrgang."""

    price: int | None = None
    price_marker: str | None = None
    count: int | None = None
    count_marker: str | None = None
    factor: float | None = None
    mfh_count: int | None = None
    mfh_count_marker: str | None = None
    mfh_factor: float | None = None


@dataclass
class YearData:
    report_year: int
    data_year: int
    pdf_url: str
    pages: dict[str, int] = field(default_factory=dict)
    areas: dict[str, AreaValues] = field(default_factory=dict)
    totals: dict[str, int | None] = field(default_factory=dict)
    headings: dict[str, str] = field(default_factory=dict)
    # Baujahresklasse -> Kennzahl -> Lagequalität -> Wert
    quality: dict[str, dict[str, dict[str, int | None]]] = field(default_factory=dict)

    @property
    def priced(self) -> dict[str, AreaValues]:
        return {k: v for k, v in self.areas.items() if v.price is not None}


@dataclass
class Report:
    source_key: str
    city: str
    publisher: str
    area_label: str
    landing_page: str
    years: list[YearData] = field(default_factory=list)
    index_series: list[tuple[int, int]] = field(default_factory=list)
    index_series_mfh: list[tuple[int, int]] = field(default_factory=list)
    index_base: str = ""
    # Normierte Standardwohnung: Jahr -> (Altbau, Neubau) als Gesamtkaufpreis
    standard_flat: list[dict] = field(default_factory=list)
    standard_flat_note: str = ""
    broker: dict = field(default_factory=dict)
    extracted_on: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    @property
    def latest(self) -> YearData:
        return self.years[-1]

    @property
    def area_years(self) -> list[YearData]:
        """Jahrgänge mit Stadtteil-Preisen -- nur die taugen für die Balkenansicht."""
        return [y for y in self.years if any(v.price is not None for v in y.areas.values())]

    @property
    def areas(self) -> list[str]:
        names: set[str] = set()
        for y in self.years:
            names.update(y.areas)
        return sorted(names)


class DownloadError(RuntimeError):
    pass


class ExtractionError(RuntimeError):
    pass


# ===========================================================================
# Download
# ===========================================================================

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def download_pdf(url: str, dest: Path, timeout: int = 90, referer: str = "") -> Path:
    """Lädt das PDF. Wirft DownloadError mit verwertbarer Diagnose."""
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        raise DownloadError(f"Netzwerkfehler beim Abruf von {url}: {exc}") from exc

    if resp.status_code != 200:
        raise DownloadError(
            f"HTTP {resp.status_code} für {url} "
            f"(Content-Type: {resp.headers.get('Content-Type', '?')})"
        )

    body = resp.content
    ctype = resp.headers.get("Content-Type", "").lower()

    if not body.startswith(b"%PDF"):
        hint = ""
        if b"<html" in body[:2000].lower() or "html" in ctype:
            hint = (" Es kam HTML statt PDF zurück -- typisch für Bot-Schutz, "
                    "eine Consent-Seite oder eine Umleitung.")
        raise DownloadError(
            f"Antwort von {url} ist kein PDF "
            f"(Content-Type: {ctype or '?'}, {len(body)} Bytes).{hint}"
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return dest


def ensure_pdf(source: Source, year: int, cache_dir: Path, refresh: bool = False,
               quiet: bool = False) -> Path:
    target = cache_dir / source.filename(year)
    if target.exists() and not refresh:
        return target
    path = download_pdf(source.url(year), target, referer=source.landing_page)
    if not quiet:
        print(f"  {source.filename(year)}: "
              f"{path.stat().st_size / 1_048_576:.1f} MB geladen")
    return path


def fetch_years(source: Source, years: Sequence[int], cache_dir: Path,
                refresh: bool = False, workers: int = 4) -> dict[int, Path | Exception]:
    """Lädt mehrere Jahrgänge parallel.

    Die Berichte sind 10-30 MB gross; nacheinander geladen dominiert die
    Wartezeit den ersten Lauf.
    """
    results: dict[int, Path | Exception] = {}
    todo = [y for y in years if refresh or not (cache_dir / source.filename(y)).exists()]
    for year in years:
        if year not in todo:
            results[year] = cache_dir / source.filename(year)

    if todo:
        print(f"→ Lade {len(todo)} Jahrgang(e) parallel …")
        with futures.ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
            jobs = {
                pool.submit(ensure_pdf, source, y, cache_dir, refresh): y
                for y in todo
            }
            for job in futures.as_completed(jobs):
                year = jobs[job]
                try:
                    results[year] = job.result()
                except (DownloadError, requests.RequestException) as exc:
                    results[year] = exc
    return results


def discover_years(source: Source, cache_dir: Path, newest: int | None = None,
                   refresh: bool = False) -> list[int]:
    """Ermittelt, welche Jahrgänge überhaupt veröffentlicht sind."""
    newest = newest or date.today().year
    available: list[int] = []
    for year in range(source.earliest_year, newest + 1):
        if (cache_dir / source.filename(year)).exists() and not refresh:
            available.append(year)
            continue
        try:
            resp = requests.head(source.url(year), headers=BROWSER_HEADERS,
                                 timeout=20, allow_redirects=True)
            if resp.status_code == 200 and "pdf" in resp.headers.get("Content-Type", ""):
                available.append(year)
        except requests.RequestException:
            continue
    return available


# ===========================================================================
# PDF-Parsing
# ===========================================================================
#
# Die Tabellen haben keine Linien, sondern mehrere nebeneinanderliegende
# Spaltenpaare aus Gebietsname (linksbündig) und Wert (rechtsbündig). Gearbeitet
# wird deshalb auf Wortkoordinaten, nicht auf Zeilentext.

INT_RE = re.compile(r"^\d{1,3}(?:\.\d{3})+$|^\d+$")
DEC_RE = re.compile(r"^\d{1,3},\d{1,3}$")
MISSING_TOKENS = {"*", "-", "–", "—", "−"}

_ROW_TOLERANCE = 7.0     # Punkte; Werte sitzen ~3pt über den Namen
# Wertespalten sind rechtsbuendig: ihre rechten Kanten streuen nur wenige Punkte.
# Eng clustern, sonst zieht ein einzelnes Fussnoten-Token die Spaltengrenze so
# weit nach rechts, dass die Namen der Nachbarspalte verschluckt werden.
_BAND_GAP = 12.0
_BAND_PAD = 6.0
_MIN_BAND_MEMBERS = 5
_NEIGHBOUR_SPAN = 2      # Seiten um einen Treffer, die mitbewertet werden


def _is_value_token(text: str, decimal: bool = False) -> bool:
    if text in MISSING_TOKENS:
        return True
    return bool(DEC_RE.match(text)) if decimal else bool(INT_RE.match(text))


def _parse_int(text: str) -> int:
    return int(text.replace(".", ""))


def _parse_number(text: str, decimal: bool) -> float | int:
    return float(text.replace(",", ".")) if decimal else _parse_int(text)


def _normalise_marker(text: str) -> str:
    return "*" if text == "*" else "-"


def _group_rows(words: Sequence[dict], tolerance: float = _ROW_TOLERANCE) -> list[list[dict]]:
    """Bündelt Wörter zu visuellen Zeilen über ihre vertikale Mitte."""
    if not words:
        return []
    enriched = sorted(
        ({"mid": (w["top"] + w["bottom"]) / 2, **w} for w in words),
        key=lambda w: (w["mid"], w["x0"]),
    )
    rows: list[list[dict]] = [[enriched[0]]]
    anchor = enriched[0]["mid"]
    for word in enriched[1:]:
        if word["mid"] - anchor > tolerance:
            rows.append([])
            anchor = word["mid"]
        rows[-1].append(word)
    return [sorted(r, key=lambda w: w["x0"]) for r in rows]


def _value_bands(rows: Iterable[list[dict]],
                 decimal: bool = False) -> list[tuple[float, float]]:
    """Findet die rechtsbündigen Wertespalten über Cluster der rechten Kanten."""
    edges = sorted(w["x1"] for row in rows for w in row
                   if _is_value_token(w["text"], decimal))
    if not edges:
        return []

    clusters: list[list[float]] = [[edges[0]]]
    for edge in edges[1:]:
        if edge - clusters[-1][-1] > _BAND_GAP:
            clusters.append([])
        clusters[-1].append(edge)

    return [
        (min(c) - _BAND_PAD, max(c) + _BAND_PAD)
        for c in clusters
        if len(c) >= _MIN_BAND_MEMBERS
    ]


def _regions(bands: Sequence[tuple[float, float]]) -> list[tuple[float, float, float]]:
    """Je Wertespalte die Zone, in der ihr Gebietsname stehen darf.

    Ohne diese Begrenzung wandern Wörter der Nachbarspalte -- oder Reste einer
    Fussnotenzeile -- in den Namen der nächsten Spalte.
    """
    regions: list[tuple[float, float, float]] = []
    left = float("-inf")
    for lo, hi in bands:
        regions.append((left, hi, lo))
        left = hi
    return regions


def _plausible_name(name: str) -> bool:
    if not name or len(name) > 60:
        return False
    # Gebietsnamen enthalten keine Ziffern und keine Formel-/Fussnotenzeichen
    if any(c.isdigit() for c in name):
        return False
    if any(c in name for c in "=,:;_/\\|"):
        return False
    letters = [c for c in name if c.isalpha()]
    if len(letters) > 4 and all(c.isupper() for c in letters):
        return False   # Kopf- und Fusszeilen sind versal gesetzt
    return any(c.isalpha() for c in name)


def parse_page(page, table: Table) -> tuple[dict[str, tuple[float | None, str | None]], tuple[float | None, str | None] | None]:
    """Liest eine Tabellenseite. Liefert {Gebiet: (Wert, Marker)} und den Gesamtwert."""
    words = [w for w in page.extract_words() if 0 <= w["x0"] and w["x1"] <= page.width]
    rows = _group_rows(words)
    bands = _value_bands(rows, table.decimal)
    if not bands:
        raise ExtractionError("Keine Wertespalten erkannt.")

    aggregate_re = re.compile(table.aggregate_re, re.I)
    entries: dict[str, tuple[int | None, str | None]] = {}
    aggregate: tuple[int | None, str | None] | None = None
    regions = _regions(bands)

    for row in rows:
        for left, right, band_lo in regions:
            segment = [w for w in row if left < w["x0"] and w["x1"] <= right + 2]

            name_parts: list[str] = []
            value_word: dict | None = None
            for word in segment:
                if (_is_value_token(word["text"], table.decimal)
                        and band_lo <= word["x1"] <= right):
                    value_word = word
                    break
                name_parts.append(word["text"])

            if value_word is None:
                continue

            name = " ".join(name_parts).strip(" .-")
            if not _plausible_name(name):
                continue

            text = value_word["text"]
            if text in MISSING_TOKENS:
                parsed: tuple[int | None, str | None] = (None, _normalise_marker(text))
            else:
                value = _parse_number(text, table.decimal)
                if not (table.min_value <= value <= table.max_value):
                    continue
                parsed = (value, None)

            if aggregate_re.match(name):
                aggregate = parsed
            elif name not in entries:
                entries[name] = parsed

    return entries, aggregate


def _score_page(pdf, index: int, table: Table) -> int:
    """Wie viele plausible Datensätze liefert diese Seite?"""
    page = pdf.pages[index]
    try:
        entries, _ = parse_page(page, table)
    except ExtractionError:
        return 0
    finally:
        page.close()
    return len(entries)


def _scan_order(n_pages: int, hint: int | None) -> list[int]:
    """Seitenreihenfolge der Suche: ringförmig um den erwarteten Ort.

    Der Seiten-Scan ist mit Abstand der teuerste Schritt (gemessen 190-330 ms je
    Seite). Von Seite 1 an zu suchen kostet bei Treffer auf Seite 44 rund acht
    Sekunden, ringförmig um einen Startwert nur etwa eine.
    """
    if hint is None:
        return list(range(n_pages))
    centre = min(max(hint - 1, 0), n_pages - 1)
    order: list[int] = []
    seen: set[int] = set()
    for delta in range(n_pages):
        for index in ((centre,) if delta == 0 else (centre - delta, centre + delta)):
            if 0 <= index < n_pages and index not in seen:
                seen.add(index)
                order.append(index)
    return order


def find_table_page(pdf, table: Table, hint: int | None = None) -> int:
    """Liefert den 0-basierten Index der echten Tabellenseite.

    Der Bericht setzt Doppelseiten: die Nachbarseite enthält dieselbe Tabelle
    noch einmal mit negativen x-Koordinaten (Bleed). Gewertet wird deshalb nicht
    der erste Überschriftentreffer, sondern die Ausbeute an Datensätzen.
    """
    heading_re = re.compile(table.heading_re, re.I)
    n_pages = len(pdf.pages)

    first: int | None = None
    for index in _scan_order(n_pages, hint if hint is not None else table.page_hint):
        page = pdf.pages[index]
        text = (page.extract_text() or "").replace("\n", " ")
        page.close()
        if heading_re.search(text):
            first = index
            break

    if first is None:
        raise ExtractionError(
            f"Überschrift der Tabelle „{table.label}“ nicht gefunden "
            f"(gesucht: /{table.heading_re}/)."
        )

    candidates = []
    for index in range(max(0, first - _NEIGHBOUR_SPAN),
                       min(n_pages, first + _NEIGHBOUR_SPAN + 1)):
        page = pdf.pages[index]
        text = (page.extract_text() or "").replace("\n", " ")
        page.close()
        if heading_re.search(text):
            candidates.append(index)

    best_score, best_index = max((_score_page(pdf, i, table), i) for i in candidates)
    if best_score == 0:
        raise ExtractionError(
            f"Tabelle „{table.label}“ gefunden, aber keine Datensätze lesbar "
            f"(Seiten {[i + 1 for i in candidates]})."
        )
    return best_index


def _heading_text(page, table: Table) -> str:
    for line in (page.extract_text() or "").split("\n"):
        if re.search(table.heading_re, line, re.I):
            return line.strip()
    return ""


def _data_year(heading: str, report_year: int) -> int:
    """Der Bericht 2025 weist die Preise des Jahres 2024 aus."""
    years = [int(y) for y in re.findall(r"\b((?:19|20)\d{2})\b", heading)]
    plausible = [y for y in years if report_year - 6 <= y < report_year]
    return max(plausible) if plausible else report_year - 1


# ===========================================================================
# Seitenindex: gefundene Tabellenseiten merken
# ===========================================================================
#
# Ohne den Index durchsucht jeder Lauf die Berichte erneut. Beim 2026er Bericht,
# der die Tabelle gar nicht mehr enthält, sind das 214 Seiten -- über eine Minute.

def _index_file(cache_dir: Path) -> Path:
    return cache_dir / "seiten-index.json"


def _load_index(cache_dir: Path) -> dict:
    try:
        return json.loads(_index_file(cache_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_index(cache_dir: Path, index: dict) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        _index_file(cache_dir).write_text(
            json.dumps(index, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError:
        pass  # Der Index ist Komfort, kein Muss


def _hint_from_index(index: dict, source: Source, year: int, table: Table) -> int | None:
    """Startwert der Seitensuche: bevorzugt aus einem Nachbarjahrgang gelernt.

    Die Berichte sind Jahr für Jahr ähnlich aufgebaut, die Tabelle wandert um
    höchstens ein bis zwei Seiten. Ein gelernter Startwert trifft deshalb fast
    immer sofort.
    """
    slot = index.get(source.key, {})
    own = slot.get(str(year), {}).get(table.key)
    if isinstance(own, int):
        return own
    neighbours = [
        (abs(int(y) - year), page)
        for y, tables in slot.items()
        if y.isdigit()
        for page in [tables.get(table.key)]
        if isinstance(page, int)
    ]
    if neighbours:
        return min(neighbours)[1]
    return table.page_hint


# ---------------------------------------------------------------------------
# Zwei Sonderformen, die nicht dem Muster "Gebiet -> Wert" folgen
# ---------------------------------------------------------------------------

QUALITY_HEADING = r"Preise\s+in\s+Euro\s+pro\s+Quadratmeter\s+Wohnfläche"
QUALITY_LEVELS = ("Schlechte", "Mäßige", "Mittlere", "Gute", "Bevorzugte")
QUALITY_METRICS = ("Minimum", "Maximum", "Mittelwert", "Anzahl")
# Nur bis zur Trennstelle suchen: der Bericht 2026 bricht die Überschrift um
# ("Preisindex von Eigentumswoh-" / "nungen"), ein Vollwort-Muster greift dort nicht.
INDEX_HEADING = r"Preisindex\s+von\s+Eigentumswoh"

_QUALITY_TABLE = Table(
    key="lage", label="Kaufpreise nach Lage", unit="€/m²",
    heading_re=QUALITY_HEADING, aggregate_re=r"^$",
    min_value=300, max_value=100_000, page_hint=42,
    marker_meanings={"*": "weniger als 3 Kauffälle", "-": "kein Wert"},
)


def parse_quality_matrix(page) -> dict[str, dict[str, dict[str, int | None]]]:
    """Liest die Tabelle „Kaufpreise pro m² Wohnfläche" nach Baujahr und Lage.

    Die Baujahresbeschriftung steht *mittig* im Vierzeilenblock, also zwischen
    Maximum und Mittelwert. Wer die Zeilen einfach von oben nach unten der
    zuletzt gesehenen Beschriftung zuordnet, schiebt Minimum und Maximum um
    einen Block nach hinten.
    """
    words = [w for w in page.extract_words() if w["x0"] >= 0]
    rows = _group_rows(words, tolerance=5.0)

    edges = sorted(w["x1"] for r in rows for w in r
                   if (INT_RE.match(w["text"]) or w["text"] == "*") and w["x0"] > 200)
    if not edges:
        raise ExtractionError("Keine Wertespalten in der Lagetabelle.")
    clusters: list[list[float]] = [[edges[0]]]
    for edge in edges[1:]:
        if edge - clusters[-1][-1] > 14:
            clusters.append([])
        clusters[-1].append(edge)
    bands = [(min(c) - 8, max(c) + 8) for c in clusters if len(c) >= 4]
    if len(bands) != len(QUALITY_LEVELS):
        raise ExtractionError(
            f"{len(bands)} Lagespalten erkannt, erwartet {len(QUALITY_LEVELS)}."
        )

    blocks: list[dict] = []
    current: dict | None = None
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        metric = next((w["text"] for w in row if w["text"] in QUALITY_METRICS), None)

        if metric == QUALITY_METRICS[0]:
            current = {"baujahr": None, "werte": {}}
            blocks.append(current)
        if current is None:
            continue

        if metric:
            values: dict[str, int | None] = {}
            for word in row:
                if not (INT_RE.match(word["text"]) or word["text"] == "*"):
                    continue
                for i, (lo, hi) in enumerate(bands):
                    if lo <= word["x1"] <= hi:
                        values[QUALITY_LEVELS[i]] = (
                            None if word["text"] == "*" else _parse_int(word["text"])
                        )
                        break
            current["werte"][metric] = values
        else:
            left = [w["text"] for w in row if w["x0"] < 110]
            label = " ".join(left)
            if left and re.search(r"\d{4}", label):
                current["baujahr"] = label

    return {b["baujahr"]: b["werte"] for b in blocks if b["baujahr"]}


def parse_index_series(page) -> list[tuple[int, int]]:
    """Liest die Indexreihe aus dem Liniendiagramm.

    Das Diagramm beschriftet jeden Datenpunkt. Die Achsenzahlen stehen alle auf
    derselben rechten Kante -- daran lassen sie sich von den Datenlabels trennen;
    zugeordnet wird anschließend über die Nähe zur Jahresbeschriftung.
    """
    words = [w for w in page.extract_words() if w["x0"] >= 0]
    years = sorted((w for w in words if re.fullmatch(r"20\d{2}", w["text"])),
                   key=lambda w: w["x0"])
    numbers = [w for w in words if re.fullmatch(r"\d{1,3}", w["text"])]
    if not years or not numbers:
        raise ExtractionError("Indexdiagramm ohne erkennbare Achsen.")

    axis_edge, axis_count = Counter(round(w["x1"]) for w in numbers).most_common(1)[0]
    if axis_count < 5:
        raise ExtractionError("Achsenspalte des Indexdiagramms nicht erkannt.")
    labels = [w for w in numbers if abs(w["x1"] - axis_edge) > 3]

    series: list[tuple[int, int]] = []
    for year in years:
        centre = (year["x0"] + year["x1"]) / 2
        nearest = min(labels, key=lambda w: abs((w["x0"] + w["x1"]) / 2 - centre))
        distance = abs((nearest["x0"] + nearest["x1"]) / 2 - centre)
        if distance <= 8:          # weiter entfernt heisst: kein Datenpunkt
            series.append((int(year["text"]), int(nearest["text"])))
    return series


STANDARD_HEADING = r"Preise\s+für\s+Standardwohnungen"
INDEX_MFH_HEADING = r"Preisindex\s+für\s+Mehrfamilien\s*häuser"
STANDARD_SQM = 80          # Bezugsgröße der Standardwohnung laut Bericht


def parse_standard_flat(page) -> list[dict]:
    """Liest die Reihe „Preise für Standardwohnungen" (Altbau gegen Neubau).

    Rechts neben der Tabelle steht die Definition der Standardwohnung, die
    ebenfalls Zahlen enthält (Baujahr 1900, 80 m², 1.200 €/m²). Ausgewertet wird
    deshalb nur der Tabellenbereich links davon.
    """
    words = [w for w in page.extract_words() if w["x0"] >= 0]
    rows = _group_rows(words, tolerance=5.0)

    out: list[dict] = []
    for row in rows:
        row.sort(key=lambda w: w["x0"])
        if not row:
            continue
        first = row[0]
        if not re.fullmatch(r"(19|20)\d{2}", first["text"]):
            continue
        values = [w for w in row[1:]
                  if INT_RE.match(w["text"]) and w["x1"] < first["x1"] + 120]
        if len(values) < 2:
            continue
        altbau, neubau = _parse_int(values[0]["text"]), _parse_int(values[1]["text"])
        if not (50_000 <= altbau <= 5_000_000 and 50_000 <= neubau <= 5_000_000):
            continue
        out.append({
            "year": int(first["text"]),
            "altbau": altbau,
            "neubau": neubau,
            "altbau_sqm": round(altbau / STANDARD_SQM),
            "neubau_sqm": round(neubau / STANDARD_SQM),
        })
    return out


def _find_by_heading(pdf, pattern: str, hint: int) -> int:
    """Seitensuche für die Sonderformen -- gleiche Ringsuche wie sonst."""
    regex = re.compile(pattern, re.I)
    for index in _scan_order(len(pdf.pages), hint):
        page = pdf.pages[index]
        text = (page.extract_text() or "").replace("\n", " ")
        page.close()
        if regex.search(text):
            return index
    raise ExtractionError(f"Überschrift nicht gefunden: /{pattern}/")


def _read_page(pdf, index: int, table: Table):
    page = pdf.pages[index]
    try:
        entries, aggregate = parse_page(page, table)
        heading = _heading_text(page, table)
    finally:
        page.close()
    return entries, aggregate, heading


def _read_table(pdf, table: Table, forced: int | None, remembered: int | None,
                index: dict, source: Source, report_year: int):
    """Liest die Tabelle -- bevorzugt von der Seite, die schon bekannt ist.

    Eine gemerkte oder erzwungene Seite wird direkt gelesen. Erst wenn dort
    nichts Brauchbares steht, wird gesucht: die Suche ist der mit Abstand
    teuerste Schritt (rund 190 ms je Seite).
    """
    known = forced if forced is not None else remembered
    if isinstance(known, int):
        try:
            entries, aggregate, heading = _read_page(pdf, known - 1, table)
            if entries:
                return known - 1, entries, aggregate, heading
        except (ExtractionError, IndexError):
            pass
        if forced is not None:
            raise ExtractionError(
                f"Auf Seite {forced} stehen keine Datensätze der Tabelle „{table.label}“."
            )

    hint = _hint_from_index(index, source, report_year, table)
    page_index = find_table_page(pdf, table, hint)
    entries, aggregate, heading = _read_page(pdf, page_index, table)
    if not entries:
        raise ExtractionError(f"Seite {page_index + 1} ohne Datensätze.")
    return page_index, entries, aggregate, heading


def extract_year(pdf_path: Path, source: Source, report_year: int,
                 cache_dir: Path | None = None,
                 page_overrides: dict[str, int] | None = None) -> YearData:
    """Liest alle konfigurierten Tabellen eines Jahrgangs aus einer PDF.

    Die Datei wird am Stück in den Speicher gelesen: auf Cloud-Laufwerken
    (Google Drive, OneDrive) ist der wahlfreie Zugriff, den pdfminer sonst
    macht, um Größenordnungen langsamer als ein sequentieller Read.
    """
    page_overrides = page_overrides or {}
    index = _load_index(cache_dir) if cache_dir else {}
    slot = index.setdefault(source.key, {}).setdefault(str(report_year), {})

    buffer = io.BytesIO(pdf_path.read_bytes())
    data = YearData(report_year=report_year, data_year=report_year - 1,
                    pdf_url=source.url(report_year))
    failures: dict[str, str] = {}

    with pdfplumber.open(buffer) as pdf:
        for table in source.tables:
            forced = page_overrides.get(table.key)
            remembered = slot.get(table.key)

            if forced is None and table.key in slot and remembered is None:
                # Aus einem früheren Lauf als "nicht enthalten" gemerkt.
                failures[table.key] = "laut Index nicht enthalten"
                if table.key == PRICE_TABLE.key:
                    break
                continue

            try:
                page_index, entries, aggregate, heading = _read_table(
                    pdf, table, forced, remembered, index, source, report_year
                )
            except (ExtractionError, IndexError) as exc:
                failures[table.key] = str(exc)
                if forced is None:
                    slot[table.key] = None
                if table.key == PRICE_TABLE.key:
                    # Fehlt die Leittabelle, ist der Jahrgang ohnehin unbrauchbar.
                    # Weitersuchen hiesse den ganzen Bericht ein zweites Mal zu
                    # durchsuchen -- bei 214 Seiten über eine Minute umsonst.
                    break
                continue

            if forced is None:
                slot[table.key] = page_index + 1

            data.pages[table.key] = page_index + 1
            data.headings[table.key] = heading
            data.totals[table.key] = aggregate[0] if aggregate else None
            if table.key == PRICE_TABLE.key:
                data.data_year = _data_year(heading, report_year)

            for name, (value, marker) in entries.items():
                slot_values = data.areas.setdefault(name, AreaValues())
                if table.key == PRICE_TABLE.key:
                    slot_values.price, slot_values.price_marker = value, marker
                elif table.key == SALES_TABLE.key:
                    slot_values.count, slot_values.count_marker = value, marker
                elif table.key == FACTOR_TABLE.key:
                    slot_values.factor = value
                elif table.key == SALES_MFH_TABLE.key:
                    slot_values.mfh_count, slot_values.mfh_count_marker = value, marker
                else:
                    slot_values.mfh_factor = value

        # --- Lagetabelle (Baujahr x Lagequalität) ---
        # Sie steht auch in Jahrgängen, die keine Stadtteiltabelle mehr führen,
        # und liefert dort das aktuellste Preisjahr.
        remembered_q = slot.get("lage")
        if not ("lage" in slot and remembered_q is None):
            try:
                q_index = (remembered_q - 1 if isinstance(remembered_q, int)
                           else _find_by_heading(pdf, QUALITY_HEADING, 42))
                data.quality = parse_quality_matrix(pdf.pages[q_index])
                pdf.pages[q_index].close()
                if data.quality:
                    slot["lage"] = q_index + 1
                    data.pages["lage"] = q_index + 1
                    if PRICE_TABLE.key in failures:
                        # Ohne Stadtteiltabelle das Bezugsjahr aus der Lagetabelle
                        heading = _heading_text(pdf.pages[q_index], _QUALITY_TABLE)
                        data.data_year = _data_year(heading, report_year)
                        pdf.pages[q_index].close()
                else:
                    slot["lage"] = None
            except (ExtractionError, IndexError) as exc:
                failures["lage"] = str(exc)
                slot["lage"] = None

    if cache_dir:
        _save_index(cache_dir, index)

    if PRICE_TABLE.key in failures and not data.quality:
        raise ExtractionError(failures[PRICE_TABLE.key])

    data.areas = dict(sorted(data.areas.items()))
    return data


def build_report(source: Source, years: Sequence[int], cache_dir: Path,
                 refresh: bool = False,
                 page_overrides: dict[str, int] | None = None,
                 local_pdf: Path | None = None) -> tuple[Report, list[str]]:
    """Baut den Gesamtbericht über alle angeforderten Jahrgänge."""
    report = Report(
        source_key=source.key,
        city=source.city,
        publisher=source.publisher,
        area_label=source.area_label,
        landing_page=source.landing_page,
    )
    notes: list[str] = []

    if local_pdf is not None:
        paths: dict[int, Path | Exception] = {years[0]: local_pdf}
    else:
        paths = fetch_years(source, years, cache_dir, refresh)

    print(f"→ Werte {len(years)} Bericht(e) aus …", flush=True)
    for year in sorted(years):
        path = paths.get(year)
        if isinstance(path, Exception) or path is None:
            notes.append(f"{year}: Download fehlgeschlagen ({path})")
            continue
        # Vor der Arbeit melden: die Seitensuche kann beim ersten Mal je Bericht
        # eine Minute dauern, und ein stummes Fenster wirkt wie ein Absturz.
        print(f"  IMB{year} … ", end="", flush=True)
        try:
            data = extract_year(path, source, year, cache_dir, page_overrides)
        except ExtractionError as exc:
            print("übersprungen")
            notes.append(f"{year}: {exc}")
            continue
        report.years.append(data)
        print(f"Preise {data.data_year}: "
              f"{len(data.priced)} von {len(data.areas)} {source.area_label}en"
              + (f", Kauffälle S.{data.pages['kauffaelle']}"
                 if "kauffaelle" in data.pages else ", ohne Kauffälle"), flush=True)

    report.years.sort(key=lambda y: y.data_year)

    # Indexreihe einmal aus dem neuesten Jahrgang, der sie führt
    for data in reversed(report.years):
        path = paths.get(data.report_year)
        if isinstance(path, Exception) or path is None:
            continue
        try:
            with pdfplumber.open(io.BytesIO(path.read_bytes())) as pdf:
                idx = _find_by_heading(pdf, INDEX_HEADING, data.pages.get("preis", 45) + 1)
                report.index_series = parse_index_series(pdf.pages[idx])
                report.index_base = "1.7.2010 = 100"
        except (ExtractionError, IndexError, OSError):
            continue
        if report.index_series:
            print(f"  Indexreihe: {len(report.index_series)} Jahre "
                  f"({report.index_series[0][0]}–{report.index_series[-1][0]})", flush=True)
            break

    # MFH-Indexreihe und die Altbau/Neubau-Reihe -- beide nur einmal, aus dem
    # neuesten Bericht, der sie führt.
    for data in reversed(report.years):
        path = paths.get(data.report_year)
        if isinstance(path, Exception) or path is None:
            continue
        try:
            with pdfplumber.open(io.BytesIO(path.read_bytes())) as pdf:
                if not report.index_series_mfh:
                    try:
                        i = _find_by_heading(pdf, INDEX_MFH_HEADING, 29)
                        report.index_series_mfh = parse_index_series(pdf.pages[i])
                    except (ExtractionError, IndexError):
                        pass
                if not report.standard_flat:
                    try:
                        i = _find_by_heading(pdf, STANDARD_HEADING, 41)
                        report.standard_flat = parse_standard_flat(pdf.pages[i])
                        report.standard_flat_note = (
                            f"Normierte Standardwohnung, {STANDARD_SQM} m², mittlere Lage, "
                            "Stadtteilfaktor 1,0. Altbau: Baujahr 1900, ohne Fahrstuhl und "
                            "Einbauküche. Neubau: Erstbezug, mit Fahrstuhl und Einbauküche."
                        )
                    except (ExtractionError, IndexError):
                        pass
        except OSError:
            continue
        if report.index_series_mfh and report.standard_flat:
            break

    if report.index_series_mfh:
        print(f"  Indexreihe Mehrfamilienhäuser: {len(report.index_series_mfh)} Jahre",
              flush=True)
    if report.standard_flat:
        sf = report.standard_flat
        print(f"  Standardwohnung Altbau/Neubau: {len(sf)} Jahre "
              f"({sf[0]['year']}–{sf[-1]['year']})", flush=True)

    report.broker = load_broker_data(Path(__file__).parent / "maklerdaten.json")

    if not report.years:
        raise ExtractionError(
            "Kein Jahrgang auswertbar.\n  " + "\n  ".join(notes or ["keine Details"])
        )
    return report, notes


# ===========================================================================
# HTML-Ausgabe
# ===========================================================================

def de(n: int | float, digits: int = 0) -> str:
    return f"{n:,.{digits}f}".replace(",", "@").replace(".", ",").replace("@", ".")


CSS = """
*, *::before, *::after { box-sizing: border-box; }
/* Muss explizit sein: .tabs/.switch setzen display:flex und wuerden hidden sonst schlagen */
[hidden] { display: none !important; }
:root {
  color-scheme: light;
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --baseline:#c3c2b7; --series:#2a78d6; --series-2:#eb6834; --series-soft:#9ec5f4;
  --hairline:rgba(11,11,11,0.10); --wash:rgba(11,11,11,0.04); --star:#eda100;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --baseline:#383835; --series:#3987e5; --series-2:#d95926; --series-soft:#1c5cab;
    --hairline:rgba(255,255,255,0.10); --wash:rgba(255,255,255,0.05); --star:#c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink-2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --baseline:#383835; --series:#3987e5; --series-2:#d95926; --series-soft:#1c5cab;
  --hairline:rgba(255,255,255,0.10); --wash:rgba(255,255,255,0.05); --star:#c98500;
}

body { margin:0; background:var(--plane); color:var(--ink); font-size:15px; line-height:1.5;
       font-family:system-ui,-apple-system,"Segoe UI",sans-serif; -webkit-font-smoothing:antialiased; }
.wrap { max-width:1000px; margin:0 auto; padding:36px 20px 72px; }

header { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start;
         justify-content:space-between; margin-bottom:26px; }
h1 { font-size:26px; line-height:1.25; margin:0 0 6px; letter-spacing:-0.01em; }
.sub { color:var(--ink-2); margin:0; font-size:15px; }
.caveat { color:var(--muted); font-size:13px; margin:10px 0 0; max-width:64ch; }

button { font:inherit; color:inherit; cursor:pointer; }
.btn { background:var(--surface); border:1px solid var(--hairline); border-radius:8px;
       padding:8px 14px; font-size:14px; white-space:nowrap; }
.btn:hover { background:var(--wash); }
.btn:focus-visible, .tab:focus-visible, .star:focus-visible { outline:2px solid var(--series); outline-offset:2px; }

.kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(158px,1fr)); gap:10px; margin-bottom:20px; }
.kpi { background:var(--surface); border:1px solid var(--hairline); border-radius:10px; padding:15px 17px; }
.kpi .label { font-size:12px; color:var(--muted); margin-bottom:4px; }
.kpi .value { font-size:24px; font-weight:600; letter-spacing:-0.02em; }
.kpi .value.hero { font-size:30px; }
.kpi .unit { font-size:13px; font-weight:400; color:var(--ink-2); margin-left:2px; }
.kpi .note { font-size:12px; color:var(--muted); margin-top:2px; }

.card { background:var(--surface); border:1px solid var(--hairline); border-radius:10px;
        padding:20px; margin-bottom:20px; }
h2 { font-size:16px; margin:0 0 2px; }
.section-note { font-size:13px; color:var(--muted); margin:0 0 16px; }

.tabs { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:12px;
        border-bottom:1px solid var(--hairline); padding-bottom:10px; }
.tab { background:none; border:1px solid transparent; border-radius:7px; padding:6px 12px;
       font-size:14px; color:var(--ink-2); }
.tab:hover { background:var(--wash); }
.tab[aria-selected="true"] { background:var(--series); color:#fff; border-color:var(--series); }

.toolbar { display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-bottom:14px; }
.toolbar input[type="search"] { flex:1 1 190px; min-width:150px; padding:7px 11px; font:inherit;
  font-size:14px; color:var(--ink); background:var(--plane);
  border:1px solid var(--hairline); border-radius:7px; }
.toolbar input::placeholder { color:var(--muted); }
.toolbar input:focus { outline:2px solid var(--series); outline-offset:1px; }
.check { display:inline-flex; align-items:center; gap:6px; font-size:13.5px; color:var(--ink-2); cursor:pointer; }
.count { font-size:13px; color:var(--muted); margin-left:auto; }

/* --- Diagramm ------------------------------------------------------- */
.chart { --name-w:172px; --val-w:112px; position:relative; }
.axis, .row { display:grid; grid-template-columns:26px var(--name-w) 1fr var(--val-w);
              align-items:center; column-gap:10px; }
.axis { height:22px; border-bottom:1px solid var(--baseline); margin-bottom:6px; }
.axis .ticks { position:relative; height:100%; }
.axis .tick { position:absolute; top:0; font-size:11px; color:var(--muted);
              transform:translateX(-50%); font-variant-numeric:tabular-nums; white-space:nowrap; }
@media (max-width:860px) { .axis .tick:not(.tick-keep) { display:none; } }

.row { height:23px; }
.row:hover { background:var(--wash); }
.row.pinned + .row:not(.pinned) { border-top:1px solid var(--hairline); }
.star { background:none; border:none; padding:0; font-size:14px; line-height:1;
        color:var(--muted); opacity:.45; }
.row:hover .star, .star.on { opacity:1; }
.star.on { color:var(--star); }
.row-name { font-size:13px; color:var(--ink-2); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.row-track { position:relative; height:100%; display:flex; align-items:center;
  background-image:repeating-linear-gradient(to right, var(--grid) 0 1px, transparent 1px var(--tick-step)); }
.row-track::after { content:""; position:absolute; left:var(--ref); top:0; bottom:0;
                    width:1px; background:var(--baseline); }
.row-bar { position:relative; height:12px; background:var(--series);
           border-radius:0 4px 4px 0; min-width:2px; }
.row-value { font-size:13px; color:var(--ink); text-align:right; font-variant-numeric:tabular-nums; }
.row-value .trend { color:var(--muted); font-size:11.5px; margin-left:6px; }
.row.hidden { display:none; }
.row.nodata .row-value { color:var(--muted); }

/* Spannen-Ansicht: ein Farbton, zwei Abstufungen */
.span-track { position:relative; height:12px; width:100%; }
.span-bar { position:absolute; top:3px; height:6px; background:var(--series-soft); border-radius:3px; }
.span-dot { position:absolute; top:1px; width:10px; height:10px; border-radius:50%;
            background:var(--series); box-shadow:0 0 0 2px var(--surface); margin-left:-5px; }

.legend-note { font-size:11.5px; color:var(--muted); margin:10px 0 0; display:flex;
               flex-wrap:wrap; gap:14px; align-items:center; }
.key-line { display:inline-block; width:14px; border-top:1px solid var(--baseline); vertical-align:middle; margin-right:5px; }
.key-span { display:inline-block; width:14px; height:5px; border-radius:3px; background:var(--series-soft);
            vertical-align:middle; margin-right:5px; }
.key-dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--series);
           vertical-align:middle; margin-right:5px; }

/* --- Fehlende Werte -------------------------------------------------- */
.missing-group { margin-bottom:18px; }
.missing-head { font-size:13px; color:var(--ink-2); margin-bottom:8px; display:flex; align-items:baseline; gap:8px; }
.marker { display:inline-flex; align-items:center; justify-content:center; min-width:20px; height:20px;
          padding:0 5px; border-radius:5px; background:var(--wash); border:1px solid var(--hairline);
          font-size:12px; color:var(--ink-2); font-weight:600; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { font-size:12.5px; color:var(--ink-2); background:var(--plane);
        border:1px solid var(--hairline); border-radius:6px; padding:3px 9px; }

/* --- Tabelle --------------------------------------------------------- */
details { border-top:1px solid var(--hairline); padding-top:14px; }
summary { cursor:pointer; font-size:14px; color:var(--ink-2); }
table { border-collapse:collapse; width:100%; margin-top:14px; font-size:13px; }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--hairline); white-space:nowrap; }
th { color:var(--muted); font-weight:500; font-size:12px; }
td.num, th.num { text-align:right; font-variant-numeric:tabular-nums; }
td.na { color:var(--muted); }
.table-scroll { overflow-x:auto; }

footer { margin-top:28px; font-size:12.5px; color:var(--muted); line-height:1.7; }
footer a { color:var(--ink-2); }

#tip { position:fixed; z-index:20; pointer-events:none; opacity:0; transition:opacity .09s ease;
       background:var(--surface); color:var(--ink); border:1px solid var(--hairline);
       border-radius:8px; padding:8px 12px; font-size:13px; line-height:1.5;
       box-shadow:0 6px 20px rgba(0,0,0,.16); white-space:nowrap; }
#tip .t-name { font-weight:600; }
#tip .t-meta { color:var(--muted); font-size:12px; }
#tip table { margin:5px 0 0; font-size:12px; }
#tip td { padding:1px 0; border:none; }
#tip td:last-child { text-align:right; padding-left:12px; font-variant-numeric:tabular-nums; }

dialog { border:1px solid var(--hairline); border-radius:12px; background:var(--surface);
         color:var(--ink); padding:22px; max-width:560px; width:calc(100% - 32px); }
dialog::backdrop { background:rgba(0,0,0,.4); }
dialog h3 { margin:0 0 10px; font-size:16px; }
dialog p { margin:0 0 12px; font-size:13.5px; color:var(--ink-2); }
code, pre { font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12.5px; }
pre { background:var(--plane); border:1px solid var(--hairline); border-radius:8px;
      padding:11px 13px; overflow-x:auto; margin:0 0 12px; }
.dialog-actions { display:flex; gap:8px; justify-content:flex-end; }
.status { font-size:13px; color:var(--ink-2); margin-top:10px; }

/* --- Indexverlauf ---------------------------------------------------- */
.index-wrap { position:relative; }
.index-wrap svg { width:100%; height:190px; display:block; overflow:visible; }
.index-line { fill:none; stroke:var(--series); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.index-dot { fill:var(--series); stroke:var(--surface); stroke-width:2; }
.index-grid { stroke:var(--grid); stroke-width:1; }
.index-axis { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
.index-label { fill:var(--ink); font-size:11.5px; font-weight:600; font-variant-numeric:tabular-nums; }

/* --- Bestand gegen Neubau: ein Farbton, zwei Abstufungen -------------- */
.std-line-alt { fill:none; stroke:var(--series); stroke-width:2; stroke-linejoin:round; }
.std-line-neu { fill:none; stroke:var(--series-2); stroke-width:2; stroke-linejoin:round; }
.std-line-alt.dim, .std-line-neu.dim { opacity:.32; }
.std-dot-alt { fill:var(--series); stroke:var(--surface); stroke-width:2; }
.std-dot-neu { fill:var(--series-2); stroke:var(--surface); stroke-width:2; }
.key-alt { display:inline-block; width:14px; border-top:2px solid var(--series);
           vertical-align:middle; margin-right:5px; }
.key-neu { display:inline-block; width:14px; border-top:2px solid var(--series-2);
           vertical-align:middle; margin-right:5px; }

/* --- Umschalter oben -------------------------------------------------- */
.switches { display:flex; flex-wrap:wrap; gap:18px; align-items:center; margin-bottom:20px; }
.switch { display:flex; align-items:center; gap:8px; }
.switch-label { font-size:12px; color:var(--muted); }
.switch .tabs { margin:0; padding:0; border:none; gap:4px; }
.note-banner { font-size:12.5px; color:var(--ink-2); background:var(--wash);
               border:1px solid var(--hairline); border-radius:8px;
               padding:9px 12px; margin:0 0 14px; }

/* --- Lagematrix: sequenzielle Rampe, ein Farbton ---------------------- */
:root {
  --heat-1:#cde2fb; --heat-2:#9ec5f4; --heat-3:#6da7ec; --heat-4:#3987e5;
  --heat-5:#256abf; --heat-6:#184f95; --heat-7:#0d366b;
  --heat-ink-lo:#0b0b0b; --heat-ink-hi:#ffffff;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --heat-1:#0d366b; --heat-2:#104281; --heat-3:#1c5cab; --heat-4:#2a78d6;
    --heat-5:#3987e5; --heat-6:#6da7ec; --heat-7:#9ec5f4;
    --heat-ink-lo:#ffffff; --heat-ink-hi:#0b0b0b;
  }
}
:root[data-theme="dark"] {
  --heat-1:#0d366b; --heat-2:#104281; --heat-3:#1c5cab; --heat-4:#2a78d6;
  --heat-5:#3987e5; --heat-6:#6da7ec; --heat-7:#9ec5f4;
  --heat-ink-lo:#ffffff; --heat-ink-hi:#0b0b0b;
}
.matrix { border-collapse:separate; border-spacing:2px; width:100%; font-size:12.5px; }
.matrix th { color:var(--muted); font-weight:500; font-size:11.5px; padding:4px 6px;
             border:none; white-space:nowrap; }
.matrix th.row-head { text-align:left; color:var(--ink-2); font-weight:400; }
.matrix td { border:none; border-radius:4px; padding:7px 8px; text-align:right;
             font-variant-numeric:tabular-nums; white-space:nowrap; }
.matrix td.empty { background:var(--wash); color:var(--muted); text-align:center; }
.matrix-note { font-size:11.5px; color:var(--muted); margin:10px 0 0; }
.scale-key { display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--muted); }
.scale-ramp { display:flex; }
.scale-ramp i { width:16px; height:10px; display:block; }

/* --- Maklerdaten: bewusst abgesetzt ---------------------------------- */
.broker { border-left:3px solid var(--baseline); padding-left:14px; }
.broker-warn { font-size:13px; color:var(--ink-2); margin:0 0 14px; }
.broker-row { display:flex; flex-wrap:wrap; align-items:baseline; gap:10px;
              padding:9px 0; border-bottom:1px solid var(--hairline); }
.broker-row:last-child { border-bottom:none; }
.broker-src { font-size:13.5px; color:var(--ink); min-width:150px; }
.broker-val { font-size:16px; font-weight:600; font-variant-numeric:tabular-nums; }
.broker-meta { font-size:12px; color:var(--muted); }
.broker-delta { font-size:12.5px; color:var(--ink-2); }
.tag { display:inline-block; font-size:11px; padding:1px 7px; border-radius:4px;
       background:var(--wash); border:1px solid var(--hairline); color:var(--ink-2); }

@media (max-width:680px) {
  .chart { --name-w:112px; --val-w:88px; }
  h1 { font-size:22px; }
  .row-name { font-size:12px; }
}
/* Sehr schmal: die Trendangabe weicht, damit die Balkenspur nutzbar bleibt.
   Der Wert steht weiter daneben, der Verlauf im Tooltip und in der Tabelle. */
@media (max-width:520px) {
  .chart { --name-w:104px; --val-w:56px; }
  .row-value .trend { display:none; }
}
"""


APP_JS = r"""
(function () {
  var DATA = JSON.parse(document.getElementById('imb-data').textContent);
  var ALL_YEARS = DATA.years;
  // Die Balkenansicht braucht Jahrgänge mit Stadtteilwerten. Der Bericht 2026
  // führt nur noch die Lagetabelle -- er zählt für die Matrix, nicht für Balken.
  var YEARS = ALL_YEARS.filter(function (y) {
    return Object.keys(y.areas).some(function (n) { return y.areas[n].p != null; });
  });
  var LAST = YEARS[YEARS.length - 1];
  var FAV_KEY = 'imb-favoriten-' + DATA.sourceKey;

  // Eine Skala über alle Jahrgänge je Objektart. Würde jedes Jahr neu skaliert,
  // sähen die Balken in jedem Jahr gleich lang aus und die Entwicklung verschwände.
  var MAX = 0, STEP = 1;

  var state = {
    objekt: 'etw',            // 'etw' | 'mfh'
    segment: 'bestand',       // 'bestand' | 'neubau'
    view: 'year',
    year: LAST.dataYear,
    query: '',
    favOnly: false,
    favs: new Set(loadFavs())
  };

  // Was die Balken zeigen, hängt an der Objektart. Für Mehrfamilienhäuser weist
  // der Bericht keine Quadratmeterpreise je Stadtteil aus -- dort sind es die
  // Verkaufszahlen, und das muss die Beschriftung auch sagen.
  var METRICS = {
    etw: { field: 'p', marker: 'm', unit: '€/m²', label: 'Mittlerer Kaufpreis',
           short: 'Kaufpreis', step: null },
    mfh: { field: 'mc', marker: 'mcm', unit: 'Verkäufe', label: 'Verkäufe',
           short: 'Verkäufe', step: null }
  };
  function metric() { return METRICS[state.objekt]; }

  function scaleFor(objekt) {
    var m = METRICS[objekt], peak = 0;
    YEARS.forEach(function (y) {
      Object.keys(y.areas).forEach(function (n) {
        var v = y.areas[n][m.field];
        if (v != null && v > peak) peak = v;
      });
    });
    var nice = [5, 10, 25, 50, 100, 250, 500, 1000, 2000, 2500, 5000, 10000, 25000];
    for (var i = 0; i < nice.length; i++) {
      if (Math.ceil(peak / nice[i]) <= 5) {
        return { step: nice[i], max: Math.ceil(peak / nice[i]) * nice[i] };
      }
    }
    return { step: nice[nice.length - 1], max: peak };
  }

  function loadFavs() {
    try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; } catch (e) { return []; }
  }
  function saveFavs() {
    try { localStorage.setItem(FAV_KEY, JSON.stringify(Array.from(state.favs))); } catch (e) {}
  }
  function fmt(n) { return n == null ? '—' : n.toLocaleString('de-DE'); }
  function yearOf(dy) {
    for (var i = 0; i < YEARS.length; i++) if (YEARS[i].dataYear === dy) return YEARS[i];
    return LAST;
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  /* --- Zeilenmodelle ------------------------------------------------ */

  function yearRows(dy) {
    var y = yearOf(dy), m = metric(), out = [];
    Object.keys(y.areas).forEach(function (name) {
      var a = y.areas[name];
      out.push({ name: name, value: a[m.field], marker: a[m.marker],
                 count: a.c, countMarker: a.cm });
    });
    out.sort(function (a, b) {
      if (a.value == null && b.value == null) return a.name.localeCompare(b.name, 'de');
      if (a.value == null) return 1;
      if (b.value == null) return -1;
      return b.value - a.value;
    });
    return out;
  }

  function spanRows() {
    var names = {};
    YEARS.forEach(function (y) { Object.keys(y.areas).forEach(function (n) { names[n] = 1; }); });
    var out = Object.keys(names).map(function (name) {
      var series = [], min = null, max = null, first = null, last = null, m = metric();
      YEARS.forEach(function (y) {
        var a = y.areas[name], p = a ? a[m.field] : null;
        series.push({ year: y.dataYear, value: p, count: a ? a.c : null });
        if (p != null) {
          if (min == null || p < min) min = p;
          if (max == null || p > max) max = p;
          if (first == null) first = p;
          last = p;
        }
      });
      return {
        name: name, series: series, min: min, max: max, value: last,
        trend: (first != null && last != null && first !== last) ? (last / first - 1) * 100 : null,
        years: series.filter(function (s) { return s.value != null; }).length
      };
    });
    out.sort(function (a, b) {
      if (a.value == null && b.value == null) return a.name.localeCompare(b.name, 'de');
      if (a.value == null) return 1;
      if (b.value == null) return -1;
      return b.value - a.value;
    });
    return out;
  }

  /* --- Rendern ------------------------------------------------------ */

  function render() {
    var rows = state.view === 'span' ? spanRows() : yearRows(state.year);
    var q = state.query.trim().toLowerCase();
    var visible = rows.filter(function (r) {
      if (state.favOnly && !state.favs.has(r.name)) return false;
      return !q || r.name.toLowerCase().indexOf(q) !== -1;
    });
    var withValue = visible.filter(function (r) { return r.value != null; });
    var without = visible.filter(function (r) { return r.value == null; });

    withValue.sort(function (a, b) {
      var fa = state.favs.has(a.name), fb = state.favs.has(b.name);
      if (fa !== fb) return fa ? -1 : 1;
      return b.value - a.value;
    });

    var ranked = {};
    rows.filter(function (r) { return r.value != null; })
        .forEach(function (r, i) { ranked[r.name] = i + 1; });

    var sc = scaleFor(state.objekt);
    MAX = sc.max; STEP = sc.step;
    var refYear = state.view === 'span' ? LAST : yearOf(state.year);
    // Der Gesamtwert der Stadt existiert nur für Kaufpreise, nicht für Verkaufszahlen
    var total = state.objekt === 'etw' ? refYear.total : null;
    var chart = document.getElementById('chart');
    chart.style.setProperty('--tick-step', (100 / (MAX / STEP)).toFixed(4) + '%');
    chart.style.setProperty('--ref', total ? (total / MAX * 100).toFixed(4) + '%' : '-10%');

    var html = axisHtml();
    withValue.forEach(function (r) {
      html += rowHtml(r, ranked[r.name], rows.length);
    });
    chart.innerHTML = html;

    document.getElementById('count').textContent =
      withValue.length + ' ' + DATA.areaLabel + 'e'
      + (without.length ? ' · ' + without.length + ' ohne Wert' : '');

    renderMissing(without);
    renderTable(rows);
    renderKpis();
    var refKey = document.getElementById('legend-ref-wrap');
    refKey.hidden = !total;
    if (total) {
      document.getElementById('legend-ref').textContent =
        DATA.city + ' gesamt ' + fmt(total) + ' ' + metric().unit
        + (state.view === 'span' ? ' (' + LAST.dataYear + ')' : '');
    }
    renderSegmentNote();
  }

  function renderSegmentNote() {
    var note = document.getElementById('segment-note');
    if (state.objekt === 'mfh') {
      note.hidden = false;
      note.textContent = 'Mehrfamilienhäuser: der Bericht weist je ' + DATA.areaLabel
        + ' nur Verkaufszahlen aus, keine Quadratmeterpreise. Preise nach Lage stehen '
        + 'weiter unten, die Trennung Bestand/Neubau gibt es für diese Objektart nicht.';
    } else if (state.segment === 'neubau') {
      note.hidden = false;
      note.textContent = 'Die ' + DATA.areaLabel + 'tabelle des Berichts ist ausdrücklich '
        + '„ohne Neubau". Das Diagramm zeigt deshalb weiterhin den Bestand; Neubauwerte '
        + 'gibt es nur gesamtstädtisch — siehe „Bestand gegen Neubau" weiter unten.';
    } else {
      note.hidden = true;
    }
  }

  function axisHtml() {
    var ticks = [], n = MAX / STEP;
    for (var i = 0; i <= n; i++) {
      var keep = (i === 0 || i === n || i === Math.round(n / 2)) ? ' tick-keep' : '';
      var shift = i === 0 ? 'transform:none;' : (i === n ? 'transform:translateX(-100%);' : '');
      ticks.push('<span class="tick' + keep + '" style="left:' + (i * 100 / n).toFixed(4) + '%;'
        + shift + '">' + fmt(i * STEP) + '</span>');
    }
    return '<div class="axis" aria-hidden="true"><div></div><div></div>'
      + '<div class="ticks">' + ticks.join('') + '</div><div></div></div>';
  }

  function rowHtml(r, rank, total) {
    var fav = state.favs.has(r.name);
    var body, valueText;

    if (state.view === 'span') {
      var lo = (r.min / MAX * 100), hi = (r.max / MAX * 100);
      body = '<div class="span-track">'
        + '<div class="span-bar" style="left:' + lo.toFixed(3) + '%;width:'
        + Math.max(hi - lo, 0.2).toFixed(3) + '%"></div>'
        + '<div class="span-dot" style="left:' + (r.value / MAX * 100).toFixed(3) + '%"></div>'
        + '</div>';
      var trendText = '';
      if (r.trend != null) {
        var rounded = Math.round(r.trend);
        // Gerundete Null bekommt keinen Richtungspfeil -- sonst behauptet die
        // Anzeige eine Bewegung, die sie im selben Atemzug mit 0 % beziffert.
        trendText = '<span class="trend">'
          + (rounded === 0 ? '±0' : (rounded > 0 ? '▲' : '▼') + Math.abs(rounded))
          + '%</span>';
      }
      valueText = fmt(r.value) + trendText;
    } else {
      body = '<div class="row-bar" style="width:' + (r.value / MAX * 100).toFixed(3) + '%"></div>';
      valueText = fmt(r.value);
    }

    return '<div class="row' + (fav ? ' pinned' : '') + '" data-name="' + esc(r.name) + '"'
      + ' data-rank="' + rank + '" data-total="' + total + '">'
      + '<button class="star' + (fav ? ' on' : '') + '" data-fav="' + esc(r.name) + '"'
      + ' title="' + (fav ? 'Favorit entfernen' : 'Als Favorit merken') + '"'
      + ' aria-pressed="' + fav + '">' + (fav ? '★' : '☆') + '</button>'
      + '<div class="row-name" title="' + esc(r.name) + '">' + esc(r.name) + '</div>'
      + '<div class="row-track">' + body + '</div>'
      + '<div class="row-value">' + valueText + '</div>'
      + '</div>';
  }

  function renderMissing(rows) {
    var host = document.getElementById('missing');
    if (!rows.length) { host.innerHTML = ''; return; }
    var groups = {};
    rows.forEach(function (r) {
      var key = r.marker || '-';
      (groups[key] = groups[key] || []).push(r.name);
    });
    var html = '<h2>Ohne ausgewiesenen Preis</h2><p class="section-note">'
      + 'Der Bericht weist für diese ' + DATA.areaLabel + 'e keinen mittleren Kaufpreis aus.</p>';
    Object.keys(groups).sort().forEach(function (key) {
      var names = groups[key].sort(function (a, b) { return a.localeCompare(b, 'de'); });
      html += '<div class="missing-group"><div class="missing-head">'
        + '<span class="marker">' + (key === '*' ? '*' : '–') + '</span><span>'
        + esc(DATA.markerMeanings[key] || 'kein Wert') + ' — ' + names.length + '</span></div>'
        + '<div class="chips">' + names.map(function (n) {
            return '<span class="chip">' + esc(n) + '</span>'; }).join('') + '</div></div>';
    });
    host.innerHTML = html;
  }

  function renderKpis() {
    var y = state.view === 'span' ? LAST : yearOf(state.year);
    var m = metric();
    var rows = yearRows(y.dataYear).filter(function (r) { return r.value != null; });
    if (!rows.length) { document.getElementById('kpis').innerHTML = ''; return; }
    var top = rows[0], bottom = rows[rows.length - 1];
    var cards;

    if (state.objekt === 'mfh') {
      var summe = rows.reduce(function (a, r) { return a + r.value; }, 0);
      var idx = DATA.indexSeriesMfh || [];
      var letzt = idx.length ? idx[idx.length - 1] : null;
      cards = [
        kpi('Verkäufe gesamt', fmt(summe), '', y.dataYear + ', über alle ' + DATA.areaLabel + 'e', true),
        kpi('Meiste Verkäufe', fmt(top.value), '', top.name),
        kpi(DATA.areaLabel + 'e mit Verkäufen', fmt(rows.length), '',
            'von ' + Object.keys(y.areas).length),
        kpi('Preisindex', letzt ? fmt(letzt.value) : '—', '',
            letzt ? 'Mehrfamilienhäuser ' + letzt.year + ' (1.7.2010 = 100)' : 'nicht ausgewiesen')
      ];
    } else {
      var prev = null;
      for (var i = 0; i < YEARS.length; i++) if (YEARS[i].dataYear === y.dataYear - 1) prev = YEARS[i];
      var delta = (prev && prev.total && y.total) ? (y.total / prev.total - 1) * 100 : null;
      cards = [
        kpi(DATA.city + ' gesamt', fmt(y.total), m.unit,
            delta != null ? (delta > 0 ? '▲' : '▼') + ' ' + Math.abs(delta).toFixed(1)
              + ' % ggü. ' + (y.dataYear - 1) : 'mittlerer Kaufpreis', true),
        kpi('Teuerster ' + DATA.areaLabel, fmt(top.value), m.unit, top.name),
        kpi('Günstigster ' + DATA.areaLabel, fmt(bottom.value), m.unit, bottom.name),
        kpi('Spannweite', (top.value / bottom.value).toFixed(1) + '×', '',
            fmt(top.value - bottom.value) + ' ' + m.unit + ' Differenz'),
        kpi('Kauffälle', fmt(y.totalCount), '',
            y.totalCount ? 'Verkäufe ' + y.dataYear : 'nicht ausgewiesen')
      ];
    }
    document.getElementById('kpis').innerHTML = cards.join('');
  }

  function kpi(label, value, unit, note, hero) {
    return '<div class="kpi"><div class="label">' + esc(label) + '</div>'
      + '<div class="value' + (hero ? ' hero' : '') + '">' + value
      + (unit ? '<span class="unit"> ' + esc(unit) + '</span>' : '') + '</div>'
      + '<div class="note">' + esc(note) + '</div></div>';
  }

  function renderTable(rows) {
    var m = metric(), mfh = state.objekt === 'mfh';
    var head = '<tr><th>' + esc(DATA.areaLabel) + '</th>';
    YEARS.forEach(function (y) { head += '<th class="num">' + y.dataYear + '</th>'; });
    head += '<th class="num">' + (mfh ? 'Faktor MFH ' : 'Kauffälle ') + LAST.dataYear + '</th>'
          + '<th class="num">' + (mfh ? 'ETW-Preis ' : 'Faktor ') + LAST.dataYear + '</th></tr>';

    var body = rows.map(function (r) {
      var cells = '<td>' + esc(r.name) + '</td>';
      YEARS.forEach(function (y) {
        var a = y.areas[r.name], v = a ? a[m.field] : null;
        cells += v != null
          ? '<td class="num">' + fmt(v) + '</td>'
          : '<td class="num na">' + (a && a[m.marker] === '*' ? '*' : '–') + '</td>';
      });
      var la = LAST.areas[r.name] || {};
      var c1 = mfh ? la.mf : la.c, c2 = mfh ? la.p : la.f;
      cells += c1 != null
        ? '<td class="num">' + (mfh ? c1.toLocaleString('de-DE', { minimumFractionDigits: 2 })
                                    : fmt(c1)) + '</td>'
        : '<td class="num na">–</td>';
      cells += c2 != null
        ? '<td class="num">' + (mfh ? fmt(c2)
              : c2.toLocaleString('de-DE', { minimumFractionDigits: 2 })) + '</td>'
        : '<td class="num na">–</td>';
      return '<tr>' + cells + '</tr>';
    }).join('');
    document.getElementById('table-head').innerHTML = head;
    document.getElementById('table-body').innerHTML = body;
  }

  /* --- Tooltip ------------------------------------------------------ */

  var tip = document.getElementById('tip');

  function tipHtml(name, rank, total) {
    var rows = '', head = '';
    if (state.view === 'span') {
      var mm = metric();
      YEARS.forEach(function (y) {
        var a = y.areas[name], v = a ? a[mm.field] : null;
        rows += '<tr><td>' + y.dataYear + '</td><td>'
          + (v != null ? fmt(v) : (a && a[mm.marker] === '*' ? '*' : '–')) + '</td></tr>';
      });
      head = '<div class="t-meta">Verlauf in ' + esc(metric().unit) + '</div>';
    } else {
      var y = yearOf(state.year), a = y.areas[name] || {}, m = metric();
      var v = a[m.field];
      head = '<div>' + (v != null ? fmt(v) + ' ' + esc(m.unit) : 'kein Wert') + '</div>';
      if (state.objekt === 'mfh') {
        if (a.mf != null) {
          rows += '<tr><td>Stadtteilfaktor MFH</td><td>'
            + a.mf.toLocaleString('de-DE', { minimumFractionDigits: 2 }) + '</td></tr>';
        }
        if (a.p != null) {
          rows += '<tr><td>ETW-Preis</td><td>' + fmt(a.p) + ' €/m²</td></tr>';
        }
      } else {
        rows += '<tr><td>Kauffälle</td><td>' + (a.c != null ? fmt(a.c) : '–') + '</td></tr>';
        if (a.f != null) {
          rows += '<tr><td>Stadtteilfaktor</td><td>'
            + a.f.toLocaleString('de-DE', { minimumFractionDigits: 2 }) + '</td></tr>';
        }
        if (a.p != null && y.total) {
          rows += '<tr><td>ggü. ' + esc(DATA.city) + '</td><td>'
            + (a.p / y.total > 1 ? '+' : '−')
            + Math.abs((a.p / y.total - 1) * 100).toFixed(0) + ' %</td></tr>';
        }
      }
      rows += '<tr><td>Rang</td><td>' + rank + ' / ' + total + '</td></tr>';
    }
    return '<div class="t-name">' + esc(name) + '</div>' + head
      + '<table><tbody>' + rows + '</tbody></table>';
  }

  document.getElementById('chart').addEventListener('mousemove', function (ev) {
    var row = ev.target.closest('.row');
    if (!row || ev.target.closest('.star')) { tip.style.opacity = 0; return; }
    tip.innerHTML = tipHtml(row.dataset.name, row.dataset.rank, row.dataset.total);
    tip.style.opacity = 1;
    var box = tip.getBoundingClientRect();
    var x = ev.clientX + 16, y = ev.clientY + 16;
    if (x + box.width > window.innerWidth - 8) x = ev.clientX - box.width - 16;
    if (y + box.height > window.innerHeight - 8) y = ev.clientY - box.height - 16;
    tip.style.left = x + 'px'; tip.style.top = Math.max(8, y) + 'px';
  });
  document.getElementById('chart').addEventListener('mouseleave', function () { tip.style.opacity = 0; });

  /* --- Bedienung ---------------------------------------------------- */

  document.getElementById('chart').addEventListener('click', function (ev) {
    var star = ev.target.closest('.star');
    if (!star) return;
    var name = star.dataset.fav;
    if (state.favs.has(name)) state.favs.delete(name); else state.favs.add(name);
    saveFavs();
    render();
  });

  document.getElementById('tabs').addEventListener('click', function (ev) {
    var tab = ev.target.closest('.tab');
    if (!tab) return;
    Array.prototype.forEach.call(this.querySelectorAll('.tab'), function (t) {
      t.setAttribute('aria-selected', t === tab);
    });
    if (tab.dataset.view === 'span') { state.view = 'span'; }
    else { state.view = 'year'; state.year = parseInt(tab.dataset.year, 10); }
    document.getElementById('span-keys').hidden = state.view !== 'span';
    render();
  });

  document.getElementById('objekt-tabs').addEventListener('click', function (ev) {
    var tab = ev.target.closest('.tab');
    if (!tab) return;
    Array.prototype.forEach.call(this.querySelectorAll('.tab'), function (t) {
      t.setAttribute('aria-selected', t === tab);
    });
    state.objekt = tab.dataset.objekt;
    document.getElementById('segment-tabs-wrap').hidden = state.objekt === 'mfh';
    document.getElementById('chart-title').textContent =
      (state.objekt === 'mfh' ? 'Verkäufe' : 'Kaufpreise') + ' nach ' + DATA.areaLabel;
    render(); renderIndex(); renderStandard(); renderMatrix(
      matrixYears().length ? matrixYears()[matrixYears().length - 1].dataYear : LAST.dataYear);
  });

  document.getElementById('segment-tabs').addEventListener('click', function (ev) {
    var tab = ev.target.closest('.tab');
    if (!tab) return;
    Array.prototype.forEach.call(this.querySelectorAll('.tab'), function (t) {
      t.setAttribute('aria-selected', t === tab);
    });
    state.segment = tab.dataset.segment;
    render(); renderStandard();
  });

  document.getElementById('search').addEventListener('input', function () {
    state.query = this.value; render();
  });
  document.getElementById('fav-only').addEventListener('change', function () {
    state.favOnly = this.checked; render();
  });

  /* --- Indexverlauf -------------------------------------------------- */

  function renderIndex() {
    var host = document.getElementById('index-card');
    var pts = (state.objekt === 'mfh' ? DATA.indexSeriesMfh : DATA.indexSeries) || [];
    var mfh = state.objekt === 'mfh';
    document.getElementById('index-title').textContent =
      mfh ? 'Preisentwicklung Mehrfamilienhäuser' : 'Preisentwicklung Eigentumswohnungen';
    document.getElementById('index-sub').textContent =
      'Amtlicher Preisindex für ' + (mfh ? 'Mehrfamilienhäuser' : 'Eigentumswohnungen')
      + ', qualitätsbereinigt und weiter zurückreichend als die Stadtteiltabellen.';
    if (pts.length < 2) { host.hidden = true; return; }

    var W = 760, H = 190, padL = 34, padR = 26, padT = 20, padB = 26;
    var vals = pts.map(function (p) { return p.value; });
    var lo = Math.floor(Math.min.apply(null, vals) / 20) * 20 - 20;
    var hi = Math.ceil(Math.max.apply(null, vals) / 20) * 20;
    var x = function (i) { return padL + i * (W - padL - padR) / (pts.length - 1); };
    var y = function (v) { return padT + (hi - v) / (hi - lo) * (H - padT - padB); };

    var grid = '', ticks = 4;
    for (var g = 0; g <= ticks; g++) {
      var gv = lo + (hi - lo) * g / ticks, gy = y(gv);
      grid += '<line class="index-grid" x1="' + padL + '" y1="' + gy.toFixed(1)
        + '" x2="' + (W - padR) + '" y2="' + gy.toFixed(1) + '"/>'
        + '<text class="index-axis" x="' + (padL - 7) + '" y="' + (gy + 3.5).toFixed(1)
        + '" text-anchor="end">' + Math.round(gv) + '</text>';
    }

    var path = pts.map(function (p, i) {
      return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(p.value).toFixed(1);
    }).join(' ');

    var marks = '', peak = Math.max.apply(null, vals);
    pts.forEach(function (p, i) {
      marks += '<circle class="index-dot" cx="' + x(i).toFixed(1) + '" cy="'
        + y(p.value).toFixed(1) + '" r="3.5"/>';
      marks += '<text class="index-axis" x="' + x(i).toFixed(1) + '" y="' + (H - 6)
        + '" text-anchor="middle">' + String(p.year).slice(2) + '</text>';
      // Sparsam beschriften: Anfang, Ende und der Höchststand
      if (i === 0 || i === pts.length - 1 || p.value === peak) {
        marks += '<text class="index-label" x="' + x(i).toFixed(1) + '" y="'
          + (y(p.value) - 9).toFixed(1) + '" text-anchor="middle">' + p.value + '</text>';
      }
    });

    document.getElementById('index-plot').innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" '
      + 'aria-label="Preisindex ' + pts[0].year + ' bis ' + pts[pts.length - 1].year + '">'
      + grid + '<path class="index-line" d="' + path + '"/>' + marks + '</svg>';

    var first = pts[0], last = pts[pts.length - 1];
    document.getElementById('index-note').textContent =
      'Basis ' + DATA.indexBase + '. Von ' + first.year + ' (' + first.value + ') bis '
      + last.year + ' (' + last.value + '): '
      + (last.value >= first.value ? '+' : '−')
      + Math.abs(Math.round((last.value / first.value - 1) * 100)) + ' %. '
      + 'Der Index ist qualitätsbereinigt und folgt deshalb nicht exakt den Mittelwerten oben.';
  }

  /* --- Lagematrix ---------------------------------------------------- */

  function matrixYears() {
    return ALL_YEARS.filter(function (y) { return y.quality && Object.keys(y.quality).length; });
  }

  function renderMatrix(dataYear) {
    var host = document.getElementById('matrix-card');
    var avail = matrixYears();
    if (!avail.length) { host.hidden = true; return; }
    var y = avail.filter(function (v) { return v.dataYear === dataYear; })[0]
            || avail[avail.length - 1];

    var levels = DATA.qualityLevels, classes = Object.keys(y.quality);
    var all = [];
    classes.forEach(function (bj) {
      levels.forEach(function (l) {
        var v = (y.quality[bj].Mittelwert || {})[l];
        if (v != null) all.push(v);
      });
    });
    var lo = Math.min.apply(null, all), hi = Math.max.apply(null, all);

    var head = '<tr><th class="row-head">Baujahre</th>'
      + levels.map(function (l) { return '<th>' + esc(l) + ' Lage</th>'; }).join('') + '</tr>';

    var body = classes.map(function (bj) {
      var cells = levels.map(function (l) {
        var m = y.quality[bj].Mittelwert || {}, n = (y.quality[bj].Anzahl || {})[l];
        var v = m[l];
        if (v == null) {
          return '<td class="empty" title="' + (n != null ? n + ' Kauffälle, '
            + 'kein Mittelwert ausgewiesen' : 'keine Angabe') + '">—</td>';
        }
        var step = Math.min(7, Math.max(1, Math.round(1 + (v - lo) / (hi - lo || 1) * 6)));
        var ink = step >= 4 ? 'var(--heat-ink-hi)' : 'var(--heat-ink-lo)';
        return '<td style="background:var(--heat-' + step + ');color:' + ink + '"'
          + ' title="' + esc(bj) + ', ' + esc(l) + ' Lage: ' + fmt(v) + ' ' + esc(DATA.unit)
          + (n != null ? ', ' + fmt(n) + ' Kauffälle' : '') + '">' + fmt(v) + '</td>';
      }).join('');
      return '<tr><th class="row-head">' + esc(bj) + '</th>' + cells + '</tr>';
    }).join('');

    document.getElementById('matrix-head').innerHTML = head;
    document.getElementById('matrix-body').innerHTML = body;
    document.getElementById('matrix-range').textContent = fmt(lo) + ' bis ' + fmt(hi) + ' ' + DATA.unit;
    document.getElementById('matrix-note').textContent =
      'Mittelwerte ' + y.dataYear + ' in ' + DATA.unit + '. „—" heißt: weniger als 3 Kauffälle, '
      + 'deshalb kein Mittelwert. Zahlen je Zelle im Tooltip mit Fallzahl.';

    var tabs = avail.map(function (v) {
      return '<button class="tab" role="tab" data-myear="' + v.dataYear + '" aria-selected="'
        + (v === y) + '">' + v.dataYear + '</button>';
    }).join('');
    document.getElementById('matrix-tabs').innerHTML = tabs;
  }

  document.getElementById('matrix-tabs').addEventListener('click', function (ev) {
    var tab = ev.target.closest('.tab');
    if (tab) renderMatrix(parseInt(tab.dataset.myear, 10));
  });

  /* --- Bestand gegen Neubau ------------------------------------------ */

  function renderStandard() {
    var host = document.getElementById('standard-card');
    var rows = DATA.standardFlat || [];
    if (!rows.length || state.objekt === 'mfh') { host.hidden = true; return; }
    host.hidden = false;

    var W = 760, H = 210, padL = 44, padR = 26, padT = 22, padB = 26;
    var vals = [];
    rows.forEach(function (r) { vals.push(r.altbau_sqm, r.neubau_sqm); });
    var hi = Math.ceil(Math.max.apply(null, vals) / 1000) * 1000;
    var lo = 0;
    var x = function (i) { return padL + i * (W - padL - padR) / (rows.length - 1); };
    var y = function (v) { return padT + (hi - v) / (hi - lo) * (H - padT - padB); };

    var grid = '';
    for (var g = 0; g <= 4; g++) {
      var gv = hi * g / 4, gy = y(gv);
      grid += '<line class="index-grid" x1="' + padL + '" y1="' + gy.toFixed(1)
        + '" x2="' + (W - padR) + '" y2="' + gy.toFixed(1) + '"/>'
        + '<text class="index-axis" x="' + (padL - 7) + '" y="' + (gy + 3.5).toFixed(1)
        + '" text-anchor="end">' + fmt(Math.round(gv)) + '</text>';
    }

    function line(key, cls) {
      return rows.map(function (r, i) {
        return (i ? 'L' : 'M') + x(i).toFixed(1) + ' ' + y(r[key]).toFixed(1);
      }).join(' ');
    }

    var marks = '';
    rows.forEach(function (r, i) {
      marks += '<text class="index-axis" x="' + x(i).toFixed(1) + '" y="' + (H - 6)
        + '" text-anchor="middle">' + String(r.year).slice(2) + '</text>';
    });
    // Nur die Enden beschriften -- zwei Reihen mal elf Punkte wären Rauschen.
    var lastRow = rows[rows.length - 1];
    ['altbau_sqm', 'neubau_sqm'].forEach(function (key, k) {
      var i = rows.length - 1;
      marks += '<circle class="' + (k ? 'std-dot-neu' : 'std-dot-alt') + '" cx="'
        + x(i).toFixed(1) + '" cy="' + y(lastRow[key]).toFixed(1) + '" r="4"/>'
        + '<text class="index-label" x="' + (x(i) - 6).toFixed(1) + '" y="'
        + (y(lastRow[key]) - 10).toFixed(1) + '" text-anchor="end">'
        + fmt(lastRow[key]) + '</text>';
    });

    var dimAlt = state.segment === 'neubau' ? ' dim' : '';
    var dimNeu = state.segment === 'bestand' ? ' dim' : '';
    document.getElementById('standard-plot').innerHTML =
      '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none" role="img" '
      + 'aria-label="Standardwohnung Bestand gegen Neubau">' + grid
      + '<path class="std-line-alt' + dimAlt + '" d="' + line('altbau_sqm') + '"/>'
      + '<path class="std-line-neu' + dimNeu + '" d="' + line('neubau_sqm') + '"/>'
      + marks + '</svg>';

    var aufschlag = Math.round((lastRow.neubau / lastRow.altbau - 1) * 100);
    var first = rows[0];
    var aufschlagFrueher = Math.round((first.neubau / first.altbau - 1) * 100);
    document.getElementById('standard-note').textContent =
      lastRow.year + ': Bestand ' + fmt(lastRow.altbau_sqm) + ' €/m², Neubau '
      + fmt(lastRow.neubau_sqm) + ' €/m² — ein Neubauaufschlag von ' + aufschlag + ' %, '
      + first.year + ' waren es ' + aufschlagFrueher + ' %. ' + DATA.standardFlatNote;
  }

  /* --- Maklerdaten --------------------------------------------------- */

  function renderBroker() {
    var host = document.getElementById('broker-card');
    var b = DATA.broker || {};
    if (!b.eintraege || !b.eintraege.length) { host.hidden = true; return; }

    var amtlich = LAST.total, amtlichJahr = LAST.dataYear;
    var rows = b.eintraege.map(function (e) {
      var keys = Object.keys(e.werte || {});
      var basis = '<span class="tag">' + esc(e.art || '?') + '</span>'
        + (e.datenbasis ? ' <span class="broker-meta">' + esc(e.datenbasis) + '</span>' : '');

      if (!keys.length) {
        // Offener Platzhalter: die Quelle ist vorgesehen, aber noch ohne Zahlen.
        return '<div class="broker-row">'
          + '<span class="broker-src">' + esc(e.quelle)
          + (e.bericht ? ' <span class="broker-meta">· ' + esc(e.bericht) + '</span>' : '')
          + '</span>'
          + '<span class="broker-meta">noch keine Zahlen hinterlegt</span>'
          + '<span class="broker-meta">' + basis + '</span>'
          + (e.notiz ? '<span class="broker-delta">' + esc(e.notiz) + '</span>' : '')
          + (e.url ? '<a class="broker-meta" href="' + esc(e.url) + '">Quelle</a>' : '')
          + '</div>';
      }

      return keys.map(function (k) {
        var v = e.werte[k];
        var delta = amtlich ? Math.round((v / amtlich - 1) * 100) : null;
        return '<div class="broker-row">'
          + '<span class="broker-src">' + esc(e.quelle)
          + (keys.length > 1 || k !== DATA.city ? ' · ' + esc(k) : '') + '</span>'
          + '<span class="broker-val">' + fmt(v) + '</span>'
          + '<span class="broker-meta">' + esc(e.einheit || DATA.unit) + ' · ' + basis
          + (e.stand ? ' · Stand ' + esc(e.stand) : '') + '</span>'
          + (delta != null ? '<span class="broker-delta">'
              + (delta >= 0 ? '+' : '−') + Math.abs(delta) + ' % gegenüber dem amtlichen Wert '
              + amtlichJahr + ' (' + fmt(amtlich) + ')</span>' : '')
          + (e.url ? '<a class="broker-meta" href="' + esc(e.url) + '">Quelle</a>' : '')
          + '</div>';
      }).join('');
    }).join('');

    document.getElementById('broker-rows').innerHTML = rows;
    document.getElementById('broker-warn').textContent = b.hinweis || '';
  }

  /* --- Neue Abfrage -------------------------------------------------- */

  var dlg = document.getElementById('refresh-dialog');
  document.getElementById('refresh').addEventListener('click', function () {
    if (!DATA.live) { dlg.showModal(); return; }
    var btn = this, status = document.getElementById('live-status');
    btn.disabled = true; status.textContent = 'Bericht wird abgerufen und ausgewertet …';
    fetch('api/refresh', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.ok) { status.textContent = 'Fertig, Seite wird neu geladen …';
                      setTimeout(function () { location.reload(); }, 600); }
        else { status.textContent = 'Fehlgeschlagen: ' + res.error; btn.disabled = false; }
      })
      .catch(function (e) { status.textContent = 'Fehlgeschlagen: ' + e; btn.disabled = false; });
  });
  var copyBtn = document.getElementById('copy-cmd');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      navigator.clipboard.writeText(DATA.command).then(function () {
        copyBtn.textContent = 'Kopiert';
        setTimeout(function () { copyBtn.textContent = 'Befehl kopieren'; }, 1500);
      });
    });
  }
  var closeBtn = document.getElementById('close-dialog');
  if (closeBtn) closeBtn.addEventListener('click', function () { dlg.close(); });

  render();
  renderIndex();
  // Die Matrix reicht ein Jahr weiter als die Stadtteiltabelle -- also auf dem
  // neuesten verfügbaren Jahr starten, nicht auf dem der Balkenansicht.
  var mYears = matrixYears();
  renderMatrix(mYears.length ? mYears[mYears.length - 1].dataYear : LAST.dataYear);
  renderBroker();
  renderStandard();
})();
"""


def load_broker_data(path: Path) -> dict:
    """Liest die kuratierten Maklerzahlen, falls vorhanden.

    Bewusst eine gepflegte Datei statt eines Scrapers: Maklerberichte haben
    keine stabilen Jahres-URLs, wechseln jährlich das Layout und ihre
    Nutzungsbedingungen untersagen systematische Auswertung häufig. Einzelne
    Zahlen mit Quellenangabe zu übernehmen ist robust und belastbar.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = data.get("eintraege", [])
    if not entries:
        return {}
    return {"hinweis": data.get("_hinweis", ""), "eintraege": entries}


def report_payload(report: Report, live: bool, command: str) -> dict:
    """Die Daten, die als JSON in die Seite eingebettet werden."""
    return {
        "sourceKey": report.source_key,
        "city": report.city,
        "areaLabel": report.area_label,
        "unit": PRICE_TABLE.unit,
        "publisher": report.publisher,
        "landingPage": report.landing_page,
        "generatedAt": report.extracted_on,
        "live": live,
        "command": command,
        "markerMeanings": PRICE_TABLE.marker_meanings,
        "years": [
            {
                "dataYear": y.data_year,
                "reportYear": y.report_year,
                "pdfUrl": y.pdf_url,
                "pages": y.pages,
                "total": y.totals.get(PRICE_TABLE.key),
                "totalCount": y.totals.get(SALES_TABLE.key),
                "quality": y.quality,
                "areas": {
                    name: {
                        "p": v.price, "m": v.price_marker,
                        "c": v.count, "cm": v.count_marker,
                        "f": v.factor,
                        "mc": v.mfh_count, "mcm": v.mfh_count_marker,
                        "mf": v.mfh_factor,
                    }
                    for name, v in y.areas.items()
                },
            }
            for y in report.years
        ],
        "indexSeries": [{"year": y, "value": v} for y, v in report.index_series],
        "indexSeriesMfh": [{"year": y, "value": v} for y, v in report.index_series_mfh],
        "standardFlat": report.standard_flat,
        "standardFlatNote": report.standard_flat_note,
        "standardSqm": STANDARD_SQM,
        "indexBase": report.index_base,
        "broker": report.broker,
        "qualityLevels": list(QUALITY_LEVELS),
        "qualityMetrics": list(QUALITY_METRICS),
    }


def render_html(report: Report, live: bool = False, command: str = "python imb.py") -> str:
    payload = report_payload(report, live, command)
    area_years = report.area_years or report.years
    latest, earliest = area_years[-1], area_years[0]
    span = (f"{earliest.data_year}–{latest.data_year}"
            if len(area_years) > 1 else str(latest.data_year))

    tabs = "".join(
        f'<button class="tab" role="tab" data-year="{y.data_year}" '
        f'aria-selected="{str(y is latest).lower()}">{y.data_year}</button>'
        for y in area_years
    )
    if len(area_years) > 1:
        tabs += ('<button class="tab" role="tab" data-view="span" aria-selected="false">'
                 'Verlauf</button>')

    def _source_line(y: YearData) -> str:
        if PRICE_TABLE.key in y.pages:
            what = f"Stadtteiltabelle S.{y.pages[PRICE_TABLE.key]}"
        elif "lage" in y.pages:
            what = f"nur Lagetabelle S.{y.pages['lage']}, keine Stadtteilwerte"
        else:
            what = "keine ausgewertete Tabelle"
        return (f"IMB{y.report_year} (Preise {y.data_year}, {what}): "
                f'<a href="{html.escape(y.pdf_url)}">{html.escape(y.pdf_url)}</a>')

    sources = "<br>".join(_source_line(y) for y in report.years)
    landing = (f'<br>Übersicht aller Jahrgänge: <a href="{html.escape(report.landing_page)}">'
               f"{html.escape(report.landing_page)}</a>" if report.landing_page else "")

    title = f"Eigentumswohnungen {report.city} — Kaufpreise {span}"

    head = (
        "<!doctype html>\n<html lang=\"de\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>" + CSS + "</style>\n</head>\n<body>\n"
    )

    body = f"""<div class="wrap">

<header>
  <div>
    <h1>Eigentumswohnungen in {html.escape(report.city)}</h1>
    <p class="sub">Mittlere Kaufpreise je m² Wohnfläche nach
       {html.escape(report.area_label)}, {span}</p>
  </div>
  <button class="btn" id="refresh">Neue Abfrage</button>
</header>

<p class="caveat">Bestandswohnungen ohne Neubau. Quelle:
   {html.escape(report.publisher)}. Alle Jahrgänge teilen eine gemeinsame Skala,
   damit die Balken zwischen den Jahren vergleichbar bleiben.</p>
<p class="status" id="live-status"></p>

<div class="switches">
  <div class="switch">
    <span class="switch-label">Objektart</span>
    <div class="tabs" id="objekt-tabs" role="tablist">
      <button class="tab" role="tab" data-objekt="etw" aria-selected="true">Eigentumswohnungen</button>
      <button class="tab" role="tab" data-objekt="mfh" aria-selected="false">Mehrfamilienhäuser</button>
    </div>
  </div>
  <div class="switch" id="segment-tabs-wrap">
    <span class="switch-label">Marktsegment</span>
    <div class="tabs" id="segment-tabs" role="tablist">
      <button class="tab" role="tab" data-segment="bestand" aria-selected="true">Bestand</button>
      <button class="tab" role="tab" data-segment="neubau" aria-selected="false">Neubau</button>
    </div>
  </div>
</div>

<div class="kpis" id="kpis"></div>

<section class="card">
  <h2 id="chart-title">Kaufpreise nach {html.escape(report.area_label)}</h2>
  <p class="section-note">Absteigend sortiert. Favoriten stehen oben.
     „Verlauf“ zeigt die Spanne zwischen niedrigstem und höchstem Jahreswert.</p>

  <p class="note-banner" id="segment-note" hidden></p>

  <div class="tabs" id="tabs" role="tablist">{tabs}</div>

  <div class="toolbar">
    <input id="search" type="search" placeholder="{html.escape(report.area_label)} suchen …"
           aria-label="{html.escape(report.area_label)} suchen" autocomplete="off">
    <label class="check"><input type="checkbox" id="fav-only"> nur Favoriten</label>
    <span class="count" id="count"></span>
  </div>

  <div class="chart" id="chart"></div>

  <p class="legend-note">
    <span id="legend-ref-wrap"><span class="key-line"></span><span id="legend-ref"></span></span>
    <span id="span-keys" hidden>
      <span class="key-span"></span>Spanne über alle Jahre
      &nbsp;<span class="key-dot"></span>Wert {latest.data_year}
    </span>
  </p>
</section>

<section class="card" id="missing"></section>

<section class="card" id="standard-card">
  <h2>Bestand gegen Neubau</h2>
  <p class="section-note">Normierte Standardwohnung, gesamtstädtisch. Die einzige
     Stelle, an der der Bericht Bestand und Neubau direkt gegenüberstellt.</p>
  <div class="index-wrap" id="standard-plot"></div>
  <p class="legend-note">
    <span><span class="key-alt"></span>Bestand (Altbau)</span>
    <span><span class="key-neu"></span>Neubau (Erstbezug)</span>
    <span>Angaben in €/m²</span>
  </p>
  <p class="matrix-note" id="standard-note"></p>
</section>

<section class="card" id="index-card">
  <h2 id="index-title">Preisentwicklung im Langfristvergleich</h2>
  <p class="section-note" id="index-sub"></p>
  <div class="index-wrap" id="index-plot"></div>
  <p class="matrix-note" id="index-note"></p>
</section>

<section class="card" id="matrix-card">
  <h2>Kaufpreise nach Baujahr und Lagequalität</h2>
  <p class="section-note">Dieselbe Quelle, andere Schnittebene: nicht nach
     {html.escape(report.area_label)}, sondern nach Alter und Lage der Wohnung.
     Hier reicht der Bericht ein Jahr weiter als die Stadtteiltabelle.</p>
  <div class="tabs" id="matrix-tabs" role="tablist"></div>
  <div class="table-scroll">
    <table class="matrix">
      <thead id="matrix-head"></thead>
      <tbody id="matrix-body"></tbody>
    </table>
  </div>
  <p class="matrix-note" id="matrix-note"></p>
  <p class="legend-note">
    <span class="scale-key">niedrig
      <span class="scale-ramp"><i style="background:var(--heat-1)"></i><i style="background:var(--heat-2)"></i><i style="background:var(--heat-3)"></i><i style="background:var(--heat-4)"></i><i style="background:var(--heat-5)"></i><i style="background:var(--heat-6)"></i><i style="background:var(--heat-7)"></i></span>
      hoch <span id="matrix-range"></span></span>
  </p>
</section>

<section class="card" id="broker-card">
  <h2>Zum Vergleich: Angebotspreise Dritter</h2>
  <p class="section-note">Bewusst getrennt gehalten und nicht mit den amtlichen
     Werten verrechnet.</p>
  <div class="broker">
    <p class="broker-warn" id="broker-warn"></p>
    <div id="broker-rows"></div>
  </div>
</section>

<section class="card">
  <details>
    <summary>Alle Werte als Tabelle</summary>
    <div class="table-scroll">
      <table>
        <thead id="table-head"></thead>
        <tbody id="table-body"></tbody>
      </table>
    </div>
  </details>
</section>

<footer>
  {sources}{landing}<br>
  Erstellt am {html.escape(report.extracted_on)}.
  „*“ = weniger als 3 Kauffälle, deshalb keine Angabe. „–“ = im Bericht kein Wert ausgewiesen.<br>
  Die Auswertung ist deterministisch: kein Sprachmodell beteiligt, derselbe Bericht
  ergibt immer dieselben Zahlen.
</footer>

</div>

<div id="tip" role="status" aria-live="polite"></div>

<dialog id="refresh-dialog">
  <h3>Neue Abfrage starten</h3>
  <p>Diese Datei ist eine statische Momentaufnahme und kann die Berichte nicht selbst
     abrufen. Führe dazu im Projektordner aus:</p>
  <pre>{html.escape(command)}</pre>
  <p>Mit <code>python imb.py --serve</code> läuft ein lokaler Server, in dem dieser
     Knopf die Abfrage direkt auslöst.</p>
  <div class="dialog-actions">
    <button class="btn" id="copy-cmd">Befehl kopieren</button>
    <button class="btn" id="close-dialog">Schließen</button>
  </div>
</dialog>

<script type="application/json" id="imb-data">"""

    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    tail = "</script>\n<script>" + APP_JS + "</script>\n</body>\n</html>\n"
    return head + body + data_json + tail


# ===========================================================================
# Serve-Modus: macht den Knopf "Neue Abfrage" funktionsfähig
# ===========================================================================

def serve(build, port: int = 8000, initial: str | None = None) -> int:
    """Startet einen lokalen Server, der die Seite ausliefert und neu bauen kann.

    Eine statische HTML-Datei kann weder das PDF laden (Cross-Origin) noch es
    auswerten. Wer den Knopf wirklich braucht, bekommt hier einen Prozess, der
    beides kann; ohne Server zeigt der Knopf nur den passenden Befehl.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    # Die Seite ist beim Start bereits gebaut -- nicht ein zweites Mal bauen.
    cache = {"html": initial if initial is not None else build(live=True)}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            self._send(200, cache["html"].encode("utf-8"), "text/html; charset=utf-8")

        def do_POST(self):  # noqa: N802
            if self.path.split("?")[0] != "/api/refresh":
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            try:
                cache["html"] = build(live=True)
                payload = {"ok": True}
            except Exception as exc:                     # noqa: BLE001
                payload = {"ok": False, "error": str(exc)}
            self._send(200, json.dumps(payload).encode("utf-8"),
                       "application/json; charset=utf-8")

        def log_message(self, *args):                    # Ausgabe ruhig halten
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"→ Server läuft: http://127.0.0.1:{port}   (Beenden mit Strg+C)")
    print("  Der Knopf „Neue Abfrage“ in der Seite löst dort eine echte Abfrage aus.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n→ Beendet")
    finally:
        server.server_close()
    return 0


# ===========================================================================
# CLI
# ===========================================================================

def parse_years(spec: str | None, source: Source, cache_dir: Path,
                refresh: bool) -> list[int]:
    """„all“ (Standard), „2022-2025“, „2022,2024“ oder eine einzelne Jahreszahl."""
    if not spec or spec == "all":
        found = discover_years(source, cache_dir, refresh=refresh)
        if not found:
            raise DownloadError(
                f"Keine Jahrgänge ab {source.earliest_year} gefunden. "
                "Netzwerk prüfen oder mit --pdf eine lokale Datei angeben."
            )
        return found

    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            years.update(range(int(start), int(end) + 1))
        elif part:
            years.add(int(part))
    return sorted(years)


def _command_line(args: argparse.Namespace) -> str:
    bits = [f"python {Path(__file__).name}"]
    if args.source != "hamburg":
        bits.append(f"--source {args.source}")
    if args.years:
        bits.append(f"--years {args.years}")
    if args.out:
        bits.append(f"--out {args.out}")
    return " ".join(bits)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="imb",
        description="Eigentumswohnungspreise aus den Immobilienmarktberichten "
                    "als HTML-Visualisierung.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Beispiele:\n"
            "  python imb.py                          # alle verfügbaren Jahrgänge\n"
            "  python imb.py --years 2024-2025\n"
            "  python imb.py --year 2022 --pdf ./IMB2022.pdf\n"
            "  python imb.py --serve                  # Abfrage-Knopf funktionsfähig\n"
        ),
    )
    parser.add_argument("--source", default="hamburg", choices=sorted(SOURCES),
                        help="Stadt bzw. Berichtsreihe (Standard: hamburg)")
    parser.add_argument("--years", help="„all“ (Standard), „2022-2025“ oder „2022,2024“")
    parser.add_argument("--year", type=int, help="Kurzform für einen einzelnen Jahrgang")
    parser.add_argument("--pdf", type=Path,
                        help="Lokale PDF nutzen statt herunterzuladen (ein Jahrgang)")
    parser.add_argument("--out", type=Path, help="Ziel der HTML-Datei")
    parser.add_argument("--json", type=Path, dest="json_out",
                        help="Rohdaten zusätzlich als JSON schreiben")
    parser.add_argument("--page", action="append", metavar="TABELLE=SEITE",
                        help="Tabellenseite erzwingen, z. B. --page preis=44")
    parser.add_argument("--serve", nargs="?", const=8000, type=int, metavar="PORT",
                        help="Lokalen Server starten (Standard-Port 8000)")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR,
                        help=f"Ablage der PDFs (Standard: {DEFAULT_CACHE_DIR})")
    parser.add_argument("--refresh", action="store_true",
                        help="Erneut herunterladen und Seitenindex verwerfen")
    parser.add_argument("--list-sources", action="store_true",
                        help="Verfügbare Quellen anzeigen und beenden")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.list_sources:
        for key, src in sorted(SOURCES.items()):
            tables = ", ".join(t.label for t in src.tables)
            print(f"{key:10s} {src.city} — {src.publisher}")
            print(f"{'':10s} {src.url_template}")
            print(f"{'':10s} Tabellen: {tables}")
        return 0

    source = SOURCES[args.source]
    if args.refresh:
        _index_file(args.cache_dir).unlink(missing_ok=True)

    overrides: dict[str, int] = {}
    for item in args.page or []:
        key, _, value = item.partition("=")
        if not value.isdigit():
            print(f"--page erwartet TABELLE=SEITE, bekam: {item}", file=sys.stderr)
            return 2
        overrides[key] = int(value)

    # --- Jahrgänge bestimmen ---
    local_pdf = None
    if args.pdf:
        if not args.pdf.is_file():
            print(f"Datei nicht gefunden: {args.pdf}", file=sys.stderr)
            return 2
        local_pdf = args.pdf
        year = args.year
        if year is None:
            found = re.search(r"(19|20)\d{2}", args.pdf.name)
            if not found:
                print("Jahr nicht aus dem Dateinamen ableitbar — bitte --year angeben.",
                      file=sys.stderr)
                return 2
            year = int(found.group(0))
        years = [year]
        print(f"→ Nutze lokale Datei {args.pdf} als Jahrgang {year}")
    else:
        spec = args.years or (str(args.year) if args.year else None)
        try:
            years = parse_years(spec, source, args.cache_dir, args.refresh)
        except DownloadError as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            return 1
        print(f"→ Jahrgänge: {', '.join(f'IMB{y}' for y in years)}")

    command = _command_line(args)

    def build(live: bool = False) -> str:
        report, notes = build_report(source, years, args.cache_dir, args.refresh,
                                     overrides, local_pdf)
        for note in notes:
            print(f"  Hinweis: {note}")
        build.report = report                                    # type: ignore[attr-defined]
        return render_html(report, live=live, command=command)

    # --- Bauen ---
    try:
        page = build(live=bool(args.serve))
    except (ExtractionError, DownloadError) as exc:
        print(f"\nFehlgeschlagen.\n  {exc}\n\n"
              "Mögliche Auswege:\n"
              f"  PDF von Hand laden und übergeben: python {Path(__file__).name} "
              f"--year {years[-1]} --pdf ./{source.filename(years[-1])}\n"
              f"  Tabellenseite erzwingen:          python {Path(__file__).name} "
              "--page preis=44\n", file=sys.stderr)
        return 1

    report: Report = build.report                                # type: ignore[attr-defined]

    if args.serve:
        return serve(build, args.serve, page)

    out_path = args.out or Path(f"kaufpreise-{source.key}.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    print(f"→ HTML geschrieben: {out_path.resolve()}")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(report_payload(report, False, command), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"→ JSON geschrieben: {args.json_out.resolve()}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
