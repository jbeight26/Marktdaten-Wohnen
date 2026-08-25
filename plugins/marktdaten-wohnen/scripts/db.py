#!/usr/bin/env python3
"""
Der Datenspeicher: einmal auslesen, dauerhaft behalten, nur Neues nachtragen.

Warum überhaupt eine Datenbank
------------------------------
Vorher wurde bei jedem Lauf jedes PDF neu geparst. Das war langsam, es zwang
jeden Kollegen zu 70 MB Download, und es machte Frankfurt unbenutzbar -- dessen
Berichte lassen sich nicht abrufen, sie müssen von Hand abgelegt werden.

Vor allem aber ging Wissen verloren. Zwei Beispiele aus der Praxis:

* Auf daten-hamburg.de liegen nur die Berichte 2022 bis 2026. Was dort
  herausfällt, ist ohne eigenen Speicher unwiederbringlich weg.
* Die Gutachterausschüsse **korrigieren alte Jahrgänge nachträglich**. Für
  Frankfurt 2024 weichen 11 von 15 Gebieten zwischen Bericht 2025 und 2026 ab.
  Wer nur den neuesten Bericht behält, sieht davon nie etwas.

Deshalb steht die Berichtsnummer im Schlüssel: derselbe Wert aus zwei Berichten
ergibt zwei Zeilen. Die Ansicht nimmt den neuesten, die Korrektur bleibt
nachweisbar.

Aufbau
------
Eine Zeile ist ein Faktum. Ein einziges Format trägt alle Quellen -- Hamburgs
Stadtteilpreise, Wiesbadens Segmente, Kiels Weiterverkäufe, Frankfurts
Grundbuchbezirke und die von Hand gepflegten Zahlen Dritter. Eine neue Quelle
braucht kein neues Schema, nur einen Leser, der Fakten dieser Form liefert.

Wo die Datei liegt
------------------
Zwei Dateien, mit klarer Aufgabenteilung:

* **Mitgeliefert** im Plugin -- der Stand, den alle bekommen.
* **Arbeitskopie** unter ~/.local/share/marktdaten-wohnen -- wird beschrieben.

Bei jedem Start wandert Fehlendes aus der mitgelieferten in die Arbeitskopie.
Das ist der Unterschied zu einer Datei, die die andere verdeckt: neue Zahlen
aus einer Plugin-Aktualisierung kommen an, ohne eigene Einträge zu verlieren.

`sqlite3` steckt in Pythons Standardbibliothek. Bewusst: das Plugin soll ohne
zusätzliche Abhängigkeit installierbar bleiben.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

# Mitgeliefert im Plugin -- wird gelesen, nie beschrieben. Eine Aktualisierung
# des Plugins ersetzt diese Datei, deshalb darf hier nichts Eigenes stehen.
BASIS_DB = Path(__file__).parent / "daten" / "marktdaten.db"

# Arbeitskopie -- bewusst ausserhalb des Plugins, damit sie Aktualisierungen
# überlebt, und ausserhalb von Cloud-Laufwerken, die Zugriffe blockieren können.
ARBEITS_DB = Path.home() / ".local" / "share" / "marktdaten-wohnen" / "marktdaten.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS fakten (
    quelle    TEXT    NOT NULL,   -- 'hamburg', 'frankfurt', 'colliers'
    bericht   INTEGER NOT NULL,   -- Berichtsjahrgang; 0 wenn ohne
    jahr      INTEGER NOT NULL,   -- Preisjahr, auf das sich der Wert bezieht
    ebene     TEXT    NOT NULL,   -- 'gebiet' | 'stadt' | 'lage' | 'baujahr_lage'
    gebiet    TEXT    NOT NULL,   -- Gebietsname; '' bei gesamtstädtisch
    segment   TEXT    NOT NULL,   -- 'bestand','neubau','altbau',... ; '' wenn ohne
    objektart TEXT    NOT NULL,   -- 'etw' | 'mfh' | 'whgh'
    kennzahl  TEXT    NOT NULL,   -- 'preis','kauffaelle','faktor','index',...
    wert      REAL,               -- NULL, wenn der Bericht nichts ausweist
    marker    TEXT,               -- '*' oder '-' -- der Grund dafür
    einheit   TEXT,
    seite     INTEGER,            -- Fundstelle im Bericht
    methode   TEXT,               -- 'text','ocr','gerechnet','manuell'
    erfasst   TEXT,
    PRIMARY KEY (quelle, bericht, jahr, ebene, gebiet, segment, objektart, kennzahl)
);

CREATE INDEX IF NOT EXISTS fakten_zugriff
    ON fakten (quelle, kennzahl, jahr);

CREATE TABLE IF NOT EXISTS berichte (
    quelle      TEXT    NOT NULL,
    bericht     INTEGER NOT NULL,
    titel       TEXT,
    herausgeber TEXT,
    url         TEXT,
    datei       TEXT,
    hash        TEXT,             -- SHA256; erkennt stille Korrekturen am PDF
    seiten      INTEGER,
    meta        TEXT,             -- JSON: Fundseiten, OCR-Nachweis, Überschriften
    gelesen_am  TEXT,
    PRIMARY KEY (quelle, bericht)
);
"""

SPALTEN = ("quelle", "bericht", "jahr", "ebene", "gebiet", "segment",
           "objektart", "kennzahl", "wert", "marker", "einheit", "seite",
           "methode", "erfasst")


@dataclass
class Faktum:
    """Ein einzelner Wert mit allem, was ihn nachvollziehbar macht."""

    quelle: str
    jahr: int
    kennzahl: str
    wert: float | None = None
    bericht: int = 0
    ebene: str = "gebiet"
    gebiet: str = ""
    segment: str = ""
    objektart: str = "etw"
    marker: str | None = None
    einheit: str = ""
    seite: int | None = None
    methode: str = "text"
    erfasst: str = field(default_factory=lambda: date.today().isoformat())

    def als_zeile(self) -> tuple:
        return tuple(getattr(self, name) for name in SPALTEN)


def datei_hash(pfad: Path) -> str:
    """SHA256 in Blöcken -- die Berichte sind bis zu 30 MB gross."""
    h = hashlib.sha256()
    with pfad.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def oeffne(pfad: Path | None = None, nur_lesen: bool = False) -> sqlite3.Connection:
    ziel = Path(pfad) if pfad else ARBEITS_DB
    if not nur_lesen:
        ziel.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ziel)
    con.row_factory = sqlite3.Row
    if not nur_lesen:
        con.executescript(SCHEMA)
    return con


def schreibe(con: sqlite3.Connection, fakten: Iterable[Faktum]) -> int:
    """Trägt Fakten ein und ersetzt gleiche Schlüssel.

    Gleicher Schlüssel heisst: dieselbe Quelle, derselbe Bericht, dasselbe
    Preisjahr, dasselbe Gebiet. Ein erneuter Lauf über denselben Bericht ändert
    also nichts -- eine Korrektur in einem *neuen* Bericht legt dagegen eine
    zusätzliche Zeile an, statt die alte zu überschreiben.
    """
    zeilen = [f.als_zeile() for f in fakten]
    if not zeilen:
        return 0
    platzhalter = ",".join("?" * len(SPALTEN))
    con.executemany(
        f"INSERT OR REPLACE INTO fakten ({','.join(SPALTEN)}) VALUES ({platzhalter})",
        zeilen,
    )
    con.commit()
    return len(zeilen)


def merke_bericht(con: sqlite3.Connection, quelle: str, bericht: int, *,
                  titel: str = "", herausgeber: str = "", url: str = "",
                  datei: str = "", hash_: str = "", seiten: int = 0,
                  meta: dict | None = None) -> None:
    con.execute(
        "INSERT OR REPLACE INTO berichte "
        "(quelle,bericht,titel,herausgeber,url,datei,hash,seiten,meta,gelesen_am) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (quelle, bericht, titel, herausgeber, url, datei, hash_, seiten,
         json.dumps(meta or {}, ensure_ascii=False), date.today().isoformat()),
    )
    con.commit()


def bericht_meta(con: sqlite3.Connection, quelle: str, bericht: int) -> dict:
    """Beiwerk eines Berichts: Fundseiten, OCR-Nachweis, Überschriften."""
    treffer = con.execute("SELECT meta FROM berichte WHERE quelle=? AND bericht=?",
                          (quelle, bericht)).fetchone()
    if not treffer or not treffer[0]:
        return {}
    try:
        return json.loads(treffer[0])
    except ValueError:
        return {}


def schon_gelesen(con: sqlite3.Connection, quelle: str, bericht: int,
                  hash_: str) -> bool:
    """Ist dieser Bericht in genau dieser Fassung bereits ausgewertet?

    Über den Hash, nicht über die Jahreszahl: veröffentlicht ein
    Gutachterausschuss dieselbe Datei korrigiert neu, wird sie erneut gelesen.
    """
    if not hash_:
        return False
    treffer = con.execute(
        "SELECT 1 FROM berichte WHERE quelle=? AND bericht=? AND hash=?",
        (quelle, bericht, hash_),
    ).fetchone()
    if not treffer:
        return False
    # Ein Eintrag ohne zugehörige Fakten wäre eine Karteileiche -- etwa nach
    # einem Abbruch mitten im Lauf. Dann lieber neu lesen.
    hat_fakten = con.execute(
        "SELECT 1 FROM fakten WHERE quelle=? AND bericht=? LIMIT 1",
        (quelle, bericht),
    ).fetchone()
    return bool(hat_fakten)


def uebernimm_basis(con: sqlite3.Connection, basis: Path | None = None) -> int:
    """Holt Fehlendes aus der mitgelieferten Datenbank in die Arbeitskopie.

    Bewusst `INSERT OR IGNORE`: was vor Ort schon steht, bleibt unangetastet.
    So kommen neue Zahlen aus einer Plugin-Aktualisierung an, ohne eigene
    Ergänzungen zu überschreiben -- der Fehler, den eine einfach verdeckende
    Datei machen würde.
    """
    quelle_db = Path(basis) if basis else BASIS_DB
    if not quelle_db.is_file():
        return 0
    try:
        con.execute("ATTACH DATABASE ? AS basis", (str(quelle_db),))
    except sqlite3.Error:
        return 0
    try:
        vorher = con.execute("SELECT COUNT(*) FROM fakten").fetchone()[0]
        con.execute(f"INSERT OR IGNORE INTO fakten ({','.join(SPALTEN)}) "
                    f"SELECT {','.join(SPALTEN)} FROM basis.fakten")
        con.execute("INSERT OR IGNORE INTO berichte SELECT * FROM basis.berichte")
        con.commit()
        nachher = con.execute("SELECT COUNT(*) FROM fakten").fetchone()[0]
        return nachher - vorher
    except sqlite3.Error:
        return 0
    finally:
        con.execute("DETACH DATABASE basis")


def veroeffentliche(arbeits: Path | None = None, basis: Path | None = None) -> int:
    """Schreibt die Arbeitskopie in die mitgelieferte Datenbank zurück.

    Der Schritt, mit dem neu ausgelesene Zahlen den Weg zu den Kollegen
    antreten. Danach committen.
    """
    quelle = Path(arbeits) if arbeits else ARBEITS_DB
    ziel = Path(basis) if basis else BASIS_DB
    if not quelle.is_file():
        raise FileNotFoundError(f"Keine Arbeitskopie unter {quelle}")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    if ziel.exists():
        ziel.unlink()               # VACUUM INTO verlangt eine freie Zieldatei
    with closing(oeffne(quelle, nur_lesen=True)) as con:
        con.execute("VACUUM INTO ?", (str(ziel),))
        anzahl = con.execute("SELECT COUNT(*) FROM fakten").fetchone()[0]
    return anzahl


# ===========================================================================
# Abfragen für die Ausgabe
# ===========================================================================

def jahre(con: sqlite3.Connection, quelle: str, kennzahl: str = "preis",
          ebene: str = "gebiet") -> list[int]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT jahr FROM fakten WHERE quelle=? AND kennzahl=? AND ebene=? "
        "ORDER BY jahr", (quelle, kennzahl, ebene))]


def neuester_bericht(con: sqlite3.Connection, quelle: str, jahr: int,
                     ebene: str | None = None) -> int | None:
    """Aus welchem Bericht stammt der gültige Wert für dieses Preisjahr?

    Der neueste gewinnt: er enthält die nachträglich korrigierten Zahlen.

    `ebene` ist wichtiger, als es aussieht. Hamburgs Indexreihe reicht über
    zehn Jahre zurück, steht aber komplett im neuesten Bericht. Ohne
    Einschränkung auf die Ebene würde für 2021 der Bericht 2026 gelten -- und
    dessen Gebietstabelle enthält 2021 gar nicht. Das Ergebnis wären leere
    Jahrgänge.
    """
    sql = "SELECT MAX(bericht) FROM fakten WHERE quelle=? AND jahr=?"
    args: list = [quelle, jahr]
    if ebene is not None:
        sql += " AND ebene=?"
        args.append(ebene)
    treffer = con.execute(sql, args).fetchone()
    return treffer[0] if treffer and treffer[0] is not None else None


def werte(con: sqlite3.Connection, quelle: str, jahr: int, *,
          ebene: str = "gebiet", segment: str | None = None,
          objektart: str | None = None, kennzahl: str | None = None,
          bericht: int | None = None) -> list[sqlite3.Row]:
    """Fakten eines Preisjahres, standardmässig aus dem neuesten Bericht."""
    if bericht is None:
        bericht = neuester_bericht(con, quelle, jahr, ebene)
        if bericht is None:
            return []
    sql = ("SELECT * FROM fakten WHERE quelle=? AND jahr=? AND bericht=? AND ebene=?")
    args: list = [quelle, jahr, bericht, ebene]
    for spalte, wert in (("segment", segment), ("objektart", objektart),
                         ("kennzahl", kennzahl)):
        if wert is not None:
            sql += f" AND {spalte}=?"
            args.append(wert)
    return list(con.execute(sql, args))


def korrekturen(con: sqlite3.Connection, quelle: str) -> list[sqlite3.Row]:
    """Wo zwei Berichte denselben Wert unterschiedlich angeben.

    Nicht für die Anzeige gedacht, sondern für die Frage „wie verlässlich ist
    ein frisch veröffentlichter Jahrgang?“ -- die Antwort steht in den
    Abweichungen des Vorjahrs.
    """
    return list(con.execute("""
        SELECT a.jahr, a.gebiet, a.segment, a.objektart, a.kennzahl,
               a.bericht AS bericht_alt, a.wert AS wert_alt,
               b.bericht AS bericht_neu, b.wert AS wert_neu
        FROM fakten a
        JOIN fakten b ON a.quelle=b.quelle AND a.jahr=b.jahr AND a.ebene=b.ebene
                     AND a.gebiet=b.gebiet AND a.segment=b.segment
                     AND a.objektart=b.objektart AND a.kennzahl=b.kennzahl
                     AND b.bericht > a.bericht
        WHERE a.quelle=? AND a.wert IS NOT NULL AND b.wert IS NOT NULL
          AND a.wert <> b.wert
        ORDER BY a.jahr, a.gebiet
    """, (quelle,)))


def bestand(con: sqlite3.Connection) -> list[sqlite3.Row]:
    """Was steckt drin -- für die Ausgabe auf der Kommandozeile."""
    return list(con.execute("""
        SELECT quelle, COUNT(*) AS fakten,
               MIN(jahr) AS von, MAX(jahr) AS bis,
               COUNT(DISTINCT bericht) AS berichte
        FROM fakten GROUP BY quelle ORDER BY quelle
    """))
