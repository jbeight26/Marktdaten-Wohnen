---
name: marktdaten-wohnen
description: Ruft die amtlichen Immobilienmarktberichte der Gutachterausschüsse von Hamburg, Wiesbaden und Kiel ab, wertet Kaufpreise für Eigentumswohnungen und Mehrfamilienhäuser je Stadtteil aus und erzeugt daraus eine interaktive HTML-Auswertung. Nutze diese Fähigkeit bei Fragen nach Immobilienpreisen, Kaufpreisen je Stadtteil, Quadratmeterpreisen, Marktdaten Wohnen oder dem Immobilienmarktbericht, etwa "starte eine neue Abfrage der Marktdaten", "aktualisiere die Immobilienpreise", "was kosten Eigentumswohnungen in Eppendorf", "zeig mir die Kaufpreise in Wiesbaden", "wie sind die Preise in Kiel" oder "wie haben sich die Preise seit 2021 entwickelt".
---

# Marktdaten Wohnen

Wertet die Immobilienmarktberichte der Gutachterausschüsse aus und erzeugt eine
eigenständige HTML-Seite mit Kaufpreisen je Stadtteil, Verlaufsansicht,
Lagematrix und dem Vergleich Bestand gegen Neubau.

Abgedeckt sind **Hamburg, Wiesbaden und Kiel**; in der Seite schaltet man oben
zwischen den Städten um. Die Berichte sind strukturell verschieden, jede Stadt
hat deshalb einen eigenen Tabellenleser.

Die Auswertung ist deterministisch: derselbe Bericht ergibt immer dieselben
Zahlen. Kein Sprachmodell schätzt hier etwas — jede Zahl stammt aus einer
benannten PDF-Seite.

## Ablauf

### 1. Umgebung sicherstellen

Prüfe, ob die Arbeitsumgebung existiert. Lege sie andernfalls einmalig an:

```bash
VENV="$HOME/.venvs/marktdaten-wohnen"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" && "$VENV/bin/pip" install -q -r "${CLAUDE_PLUGIN_ROOT}/scripts/requirements.txt"
  # Texterkennung (nur macOS): ohne sie fehlt Hamburg 2025
  "$VENV/bin/pip" install -q -r "${CLAUDE_PLUGIN_ROOT}/scripts/requirements-ocr.txt" \
    || echo "Texterkennung nicht verfügbar — Hamburg 2025 bleibt leer."
fi
```

Sage der Person vorher, dass der erste Aufruf rund eine Minute für die
Einrichtung braucht. Weitere Aufrufe dauern Sekunden.

### 2. Auswertung starten

```bash
"$HOME/.venvs/marktdaten-wohnen/bin/python" -u "${CLAUDE_PLUGIN_ROOT}/scripts/imb.py" \
  --out "$HOME/Downloads/marktdaten-wohnen.html" \
  --json "$HOME/Downloads/marktdaten-wohnen.json"
```

Wähle die Parameter nach dem, was gefragt wurde:

| Wunsch | Parameter |
|---|---|
| alle verfügbaren Jahrgänge (Standard) | keiner |
| bestimmter Jahrgang | `--year 2025` |
| Zeitraum | `--years 2023-2025` |
| Berichte neu laden statt Zwischenspeicher | `--refresh` |
| nur bestimmte Städte | `--cities wiesbaden` oder `--cities keine` |
| andere Leitquelle | `--source <name>` |
| eigene Quellendatei | `--daten <pfad>` |

Der erste Lauf auf einem Rechner lädt rund 70 MB PDF und dauert etwa anderthalb
Minuten. Danach greift ein Zwischenspeicher und es geht in Sekunden. Kündige die
Wartezeit an, bevor du den Befehl startest.

### 3. Ergebnis liefern

Schicke die erzeugte HTML-Datei mit SendUserFile und `display: "render"`, damit
sie sofort sichtbar ist. Nenne dazu in ein bis zwei Sätzen die Kernzahl —
üblicherweise den Gesamtwert der Stadt und die Spanne zwischen teuerstem und
günstigstem Stadtteil.

### 4. Fragen zu einzelnen Zahlen beantworten

Liegt bereits eine JSON-Datei vor, beantworte Fragen daraus, statt die
Auswertung erneut zu starten. Struktur:

- `years[]` — je Jahrgang `dataYear`, `total` (Gesamtwert der Stadt),
  `totalCount` (Kauffälle), `areas{}` und `quality{}`
- `areas{}` je Stadtteil: `p` Kaufpreis €/m², `c` Kauffälle, `f` Stadtteilfaktor,
  `mc` Verkäufe Mehrfamilienhäuser, `mf` Stadtteilfaktor Mehrfamilienhäuser
- `m` bzw. `mcm` — Fehlgrund: `*` weniger als 3 Kauffälle, `-` kein Wert ausgewiesen
- `indexSeries` / `indexSeriesMfh` — Preisindizes, Basis 1.7.2010 = 100
- `standardFlat` — Bestand gegen Neubau, normierte Standardwohnung

Nenne bei jeder Zahl das Bezugsjahr. Nenne bei einzelnen Stadtteilen zusätzlich
die Kauffälle: ein Mittelwert aus 5 Verkäufen trägt weniger als einer aus 228.

## Grenzen, die du benennen musst

Erfinde keine Werte und rechne Fehlendes nicht hoch. Wenn eine Angabe fehlt,
sage warum. Die wichtigsten Fälle stehen in `references/datenlage.md` — lies die
Datei, sobald jemand nach Neubau, Mehrfamilienhäusern, fehlenden Stadtteilen
oder der Verlässlichkeit der Zahlen fragt.

Kurzfassung:

- **Neubau je Stadtteil gibt es nicht.** Die Stadtteiltabelle ist ausdrücklich
  „ohne Neubau". Der Bestand/Neubau-Vergleich existiert nur gesamtstädtisch.
- **Für Mehrfamilienhäuser gibt es keine Quadratmeterpreise je Stadtteil**,
  nur Verkaufszahlen, Stadtteilfaktoren und einen Preisindex.
- **Nicht jeder Stadtteil hat einen Wert.** Bei weniger als 3 Kauffällen weist
  der Bericht nichts aus.
- **Hamburg 2025 stammt aus einer Texterkennung.** Der Bericht 2026 setzt diese
  Tabelle als Grafik. Zwei Erkennungsmodelle mussten übereinstimmen, sonst wurde
  nichts übernommen. Sage das dazu, wenn jemand Zahlen für 2025 zitiert. Zwei
  Folgen davon: die Unterscheidung zwischen „*" und „–" entfällt, und es gibt
  für 2025 **keine Kauffälle je Stadtteil** — nenne für dieses Jahr also keine
  Stichprobengröße.
- **Wiesbadens Bezirkswerte sind gerechnet**, nicht abgelesen: gewichtet nach
  Kauffällen aus den Zellen. Der Bericht gewichtet nach Fläche und nennt deshalb
  leicht andere Gesamtwerte. Sage das, wenn jemand Wiesbadener Zahlen zitiert.
- **Frankfurt fehlt.** Zwei Gründe, nicht einer: Die Stadt sperrt automatisierte
  Downloads mit einer Cloudflare-Prüfung, und es gibt keinen Frankfurter
  Tabellenleser. Ein von Hand geladenes PDF genügt deshalb **nicht** — `--pdf`
  nutzt die Tabellendefinitionen der gewählten Quelle, und die einzige Quelle
  ist Hamburg. Nenne `--pdf` hier nicht als Ausweg.
- **Städte nicht unbesehen vergleichen.** Die Gutachterausschüsse grenzen
  unterschiedlich ab (Stadtteil gegen Stadtbezirk, andere Segmente).

## Wenn etwas schiefgeht

- **Download scheitert** — die Fehlermeldung nennt die URL. Lade das PDF im
  Browser und übergib es mit `--pdf <Pfad> --year <Jahr>`.
- **Tabelle nicht gefunden** — mit `--page preis=<Seitenzahl>` lässt sich die
  Seite erzwingen. Nennt die Fehlermeldung dagegen Seiten mit vielen
  Vektorobjekten, ist die Schrift dort in Konturen umgewandelt; dann hilft
  `--page` nicht und nur OCR käme in Frage. Behaupte in diesem Fall nicht, die
  Tabelle fehle im Bericht — sie ist nur nicht maschinell lesbar.
- **Läuft ungewöhnlich lange** — das Skript meldet jeden Schritt. Bleibt es
  stumm, liegt der Zwischenspeicher vermutlich auf einem Cloud-Laufwerk;
  `--cache-dir` auf einen lokalen Pfad setzen.
