#!/usr/bin/env python3
"""
Texterkennung als Notnagel für Berichte, deren Tabellen als Grafik gesetzt sind.

Der Immobilienmarktbericht Hamburg 2026 enthält seine Stadtteiltabellen weiterhin,
hat die Schrift dort aber in Vektorkonturen umgewandelt — 32 der 214 Seiten. Für
ein Programm ist das ein Bild. Dieses Modul rendert die betroffene Seite und liest
sie mit der Texterkennung von macOS (Apple Vision, offline, ohne Zusatzsoftware).

Weil bei Kaufpreisen eine falsch gelesene Ziffer teuer ist, wird jede Seite mit
**beiden** Erkennungsmodellen gelesen. Nur Werte, in denen beide übereinstimmen,
gelten als gesichert; sonst bricht die Auswertung lieber ab.

Optional: ohne das Paket `ocrmac` bleibt der Rest des Werkzeugs voll funktionsfähig.
"""

from __future__ import annotations

import re

VERFUEGBAR = True
try:
    import pypdfium2 as pdfium
    from ocrmac import ocrmac
except ImportError:                                   # pragma: no cover
    VERFUEGBAR = False

# Vier- und fünfstellige Beträge mit Tausenderpunkt, oder blanke Zahlen
ZAHL = re.compile(r"^\d{1,3}(?:\.\d{3})+$|^\d+$")
# Zeilen, die keine Gebietsnamen sind
MUELL = re.compile(
    r"Euro|Quadratmeter|weniger als|Kauffälle|IMMOBILIEN|^\[|Verteilung|Mittlere|Indexreihe"
    r"|keine Angabe|^=",
    re.I,
)
DPI = 300
ZEILEN_TOLERANZ = 0.006      # Anteil der Seitenhöhe


class OCRNichtVerfuegbar(RuntimeError):
    pass


class OCRUneindeutig(RuntimeError):
    pass


def _fragmente(bild, level: str) -> list[dict]:
    res = ocrmac.OCR(bild, recognition_level=level).recognize()
    frag = [
        {"t": t.strip(), "k": k, "x": b[0], "xm": b[0] + b[2] / 2,
         "y": 1 - (b[1] + b[3] / 2)}
        for t, k, b in res
    ]
    frag.sort(key=lambda f: (f["y"], f["x"]))
    return frag


def _zeilen(frag: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    letzte_y = None
    for f in frag:
        if out and letzte_y is not None and abs(f["y"] - letzte_y) < ZEILEN_TOLERANZ:
            out[-1].append(f)
        else:
            out.append([f])
            letzte_y = f["y"]
    return [sorted(z, key=lambda f: f["x"]) for z in out]


def _spaltengrenzen(frag: list[dict], spalten: int) -> tuple[float, ...]:
    """Grenzen zwischen den Spaltenpaaren aus der Verteilung der Namen ableiten."""
    if spalten <= 1:
        return ()
    return tuple(i / spalten for i in range(1, spalten))


def _zellen(bild, level: str, spalten: int, aggregate_re: re.Pattern) -> tuple[list[dict], int | None]:
    """Zellen mit ihrer Position: Spalte und y-Lage. Namen bleiben roh."""
    frag = _fragmente(bild, level)
    grenzen = _spaltengrenzen(frag, spalten)
    zellen: list[dict] = []
    gesamt: int | None = None

    for zeile in _zeilen(frag):
        eimer: dict[int, list[dict]] = {i: [] for i in range(spalten)}
        for f in zeile:
            i = sum(1 for g in grenzen if f["xm"] >= g)
            eimer[i].append(f)
        for spalte, teile in eimer.items():
            if not teile:
                continue
            namen = [f for f in teile if not ZAHL.match(f["t"])]
            werte = [f for f in teile if ZAHL.match(f["t"])]
            roh = " ".join(f["t"] for f in namen).strip()
            wert = int(werte[0]["t"].replace(".", "")) if werte else None
            if aggregate_re.search(roh):
                gesamt = wert
                continue
            zellen.append({"y": teile[0]["y"], "spalte": spalte,
                           "name": roh.strip(" .-*–"), "wert": wert})
    return zellen, gesamt


def _lies(bild, level: str, spalten: int, aggregate_re: re.Pattern
          ) -> tuple[dict[str, int | None], int | None]:
    frag = _fragmente(bild, level)
    grenzen = _spaltengrenzen(frag, spalten)
    daten: dict[str, int | None] = {}
    gesamt: int | None = None

    for zeile in _zeilen(frag):
        eimer: dict[int, list[dict]] = {i: [] for i in range(spalten)}
        for f in zeile:
            i = sum(1 for g in grenzen if f["xm"] >= g)
            eimer[i].append(f)

        for teile in eimer.values():
            namen = [f for f in teile if not ZAHL.match(f["t"])]
            werte = [f for f in teile if ZAHL.match(f["t"])]
            roh = " ".join(f["t"] for f in namen).strip()
            wert = int(werte[0]["t"].replace(".", "")) if werte else None

            if aggregate_re.search(roh):
                gesamt = wert
                continue
            name = roh.strip(" .-*–")
            if not name or len(name) < 3 or any(c.isdigit() for c in name):
                continue
            if MUELL.search(name):
                continue
            daten[name] = wert
    return daten, gesamt


def lies_gebietstabelle(pdf_pfad, seiten_index: int, *, spalten: int = 3,
                        aggregate_muster: str = r"gesamt",
                        ueberschrift_muster: str | None = None
                        ) -> tuple[dict[str, int | None], int | None, dict]:
    """Liest eine Tabelle „Gebiet -> Wert" von einer als Grafik gesetzten Seite.

    Gibt Werte, Gesamtwert und einen Prüfbericht zurück. Weichen die beiden
    Erkennungsmodelle in einem Wert voneinander ab, wird abgebrochen — lieber
    keine Zahl als eine falsche.
    """
    if not VERFUEGBAR:
        raise OCRNichtVerfuegbar(
            "Texterkennung nicht verfügbar. Nachrüsten mit:  pip install ocrmac pypdfium2"
        )

    dokument = pdfium.PdfDocument(str(pdf_pfad))
    if not (0 <= seiten_index < len(dokument)):
        raise OCRUneindeutig(f"Seite {seiten_index + 1} liegt außerhalb des PDFs.")
    bild = dokument[seiten_index].render(scale=DPI / 72).to_pil()

    if ueberschrift_muster:
        kopf = " ".join(f["t"] for f in _fragmente(bild, "accurate")[:3])
        if not re.search(ueberschrift_muster, kopf, re.I):
            raise OCRUneindeutig(
                f"Seite {seiten_index + 1} trägt nicht die erwartete Überschrift "
                f"(gelesen: „{kopf[:70]}“)."
            )

    aggregate_re = re.compile(aggregate_muster, re.I)
    genau, g_gesamt = _zellen(bild, "accurate", spalten, aggregate_re)
    schnell, s_gesamt = _zellen(bild, "fast", spalten, aggregate_re)

    # Abgleich über die Position, nicht über den Namen: das schnelle Modell
    # verstümmelt Umlaute ("Allermohe"), liest Ziffern aber zuverlässig.
    streit = []
    for zelle in genau:
        if zelle["wert"] is None:
            continue
        partner = [c for c in schnell
                   if c["spalte"] == zelle["spalte"]
                   and abs(c["y"] - zelle["y"]) < ZEILEN_TOLERANZ
                   and c["wert"] is not None]
        if partner and partner[0]["wert"] != zelle["wert"]:
            streit.append((zelle["name"], zelle["wert"], partner[0]["wert"]))
    if streit:
        raise OCRUneindeutig(
            f"Die beiden Erkennungsmodelle widersprechen sich bei {len(streit)} "
            f"Wert(en), z. B. {streit[:3]}. Kein Ergebnis übernommen."
        )
    if g_gesamt is not None and s_gesamt is not None and g_gesamt != s_gesamt:
        raise OCRUneindeutig(
            f"Gesamtwert uneinheitlich gelesen ({g_gesamt} gegen {s_gesamt})."
        )

    # Namen und Werte stammen aus dem genauen Modell; das schnelle hat nur geprüft.
    daten: dict[str, int | None] = {}
    for zelle in genau:
        name = zelle["name"]
        if not name or len(name) < 3 or any(c.isdigit() for c in name):
            continue
        if MUELL.search(name):
            continue
        daten[name] = zelle["wert"]

    geprueft = sum(
        1 for z in genau if z["wert"] is not None
        and any(c["spalte"] == z["spalte"] and abs(c["y"] - z["y"]) < ZEILEN_TOLERANZ
                and c["wert"] is not None for c in schnell)
    )
    bericht = {
        "modelle_einig": True,
        "gebiete": len(daten),
        "werte": sum(1 for v in daten.values() if v is not None),
        "davon_doppelt_bestaetigt": geprueft,
        "gesamt": g_gesamt if g_gesamt is not None else s_gesamt,
    }
    return daten, bericht["gesamt"], bericht
