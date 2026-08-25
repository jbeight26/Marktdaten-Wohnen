# Datenlage und Grenzen

Referenz für Rückfragen zu Herkunft, Reichweite und Verlässlichkeit der Zahlen.

## Woher die Zahlen kommen

Quelle ist der jährliche Immobilienmarktbericht des Gutachterausschusses für
Grundstückswerte. Grundlage sind **notariell beurkundete Kaufverträge** — die
Kaufpreissammlung erfasst gesetzlich verpflichtend jeden Verkauf. Das
unterscheidet sie grundlegend von Portal- und Maklerzahlen, die Inserate oder
ein eigenes Portfolio messen.

Angebotspreise liegen systematisch über den Abschlüssen. Gängige Portalwerte für
Hamburg nennen 6.000–6.400 €/m², der Gutachterausschuss 5.696 €/m² für 2024.
Darin stecken Angebotsaufschlag und Zeitversatz, die sich nicht sauber trennen
lassen. Beides nie mitteln oder verrechnen.

## Verfügbare Jahrgänge

Auf daten-hamburg.de liegen die Berichte **IMB2022 bis IMB2026**; ältere Jahre
sind dort nicht abrufbar. Ein Bericht weist jeweils das Vorjahr aus: IMB2025
enthält die Preise für 2024.

**IMB2026 setzt die Stadtteiltabellen als Grafik.** Die Tabellen stehen dort im
Bericht, auf denselben Seiten wie im Vorjahr, sind aber als Vektorkonturen
gesetzt statt als Text — 32 der 214 Seiten sind so gesetzt, im Vorjahr war es
eine. Seite 44 enthält 2025 noch 1.845 Textzeichen bei 60 Kurvenobjekten, 2026
nur 38 Textzeichen bei 2.546 Kurven. `--page` hilft dort nicht: es gibt auf
diesen Seiten keinen Text zum Auslesen.

**Das Preisjahr 2025 stammt deshalb aus einer Texterkennung.** Zwei
Erkennungsmodelle lesen die Seite unabhängig voneinander; übernommen wird ein
Wert nur, wenn beide ihn gleich lesen. Abgeglichen wird über die Position im
Bild, nicht über den Stadtteilnamen — das schnelle Modell liest Ziffern
zuverlässig, verstümmelt aber Umlaute. Ergebnis: 76 der 104 Stadtteile mit
Preis, Gesamtwert 5.808 €/m². Zusätzlich wurden 19 Werte von Hand am Bild
gegengeprüft, ohne Abweichung.

Zwei Einschränkungen gelten allein für 2025 und gehören in jede Antwort, die
dieses Jahr zitiert:

- **Keine Kauffälle je Stadtteil.** Die Texterkennung wird nur auf die
  Preistabelle angewandt, nicht auf die Fallzahlen. Für 2025 bleibt das Feld
  leer; die Stichprobengröße ist für dieses Jahr nicht zu beurteilen. Dasselbe
  gilt für die Verkaufszahlen der Mehrfamilienhäuser.
- **„*" und „–" sind nicht unterscheidbar.** Wo kein Wert steht, liest die
  Texterkennung nichts — welcher der beiden Gründe vorliegt, bleibt offen.

Damit umfasst die Stadtteilreihe die Preisjahre **2021 bis 2025**: 2021 bis 2024
aus dem Text der Berichte, 2025 aus der Texterkennung. Läuft das Skript mit
`--no-ocr`, oder ist die Texterkennung nicht eingerichtet — sie setzt macOS
voraus —, endet die Reihe bei 2024.

## Was es je Stadtteil gibt

| Angabe | Eigentumswohnungen | Mehrfamilienhäuser |
|---|---|---|
| Kaufpreis €/m² | ja, 2021–2025 | **nein** |
| Anzahl Kauffälle | ja, 2021–2024 | ja, 2021–2024, als Verkaufszahlen |
| Stadtteilfaktor | ja, 2021–2025 | ja, 2021–2025 |

Mehrfamilienhäuser werden über Ertragsfaktoren bewertet, nicht über
Quadratmeterpreise je Lage. Für diese Objektart zeigt das Balkendiagramm
deshalb Verkaufszahlen und benennt das auch.

## Bestand und Neubau

Die Stadtteiltabelle ist ausdrücklich **„ohne Neubau"**. Eine Neubau-Entsprechung
je Stadtteil existiert im Bericht nicht — auf Stadtteilebene ist diese Trennung
nicht möglich. Wer danach fragt, bekommt diese Antwort, keine geschätzte Zahl.

Gesamtstädtisch stellt der Bericht beides gegenüber, über eine normierte
Standardwohnung (80 m², mittlere Lage, Stadtteilfaktor 1,0):

- Altbau: Baujahr 1900, 1. Obergeschoss, ohne Fahrstuhl und Einbauküche
- Neubau: Erstbezug, 1. Obergeschoss, mit Fahrstuhl und Einbauküche

Der Neubauaufschlag lag 2015 bei 37 %, 2022 bei 28 % und 2025 bei 53 %:
Bestandspreise gaben nach der Zinswende deutlich nach, Neubaupreise nicht.

Diese Werte sind **normiert**, nicht der Marktdurchschnitt. Sie beantworten
„was kostet dieselbe Wohnung heute gegenüber früher", nicht „was kostet eine
beliebige Neubauwohnung".

## Fehlende Werte

- `*` — weniger als 3 Kauffälle, deshalb keine Angabe. So im Bericht definiert.
- `-` — kein Wert ausgewiesen. Der Bericht erklärt das Zeichen nicht; betroffen
  sind durchweg Industrie- und Randlagen ohne Wohnungsmarkt, etwa Billbrook,
  Steinwerder oder Neuwerk.

Von 104 Stadtteilen haben je nach Jahr 70 bis 76 einen Preis.

## Stichprobengröße beachten

Die Kauffälle sind wichtiger, als sie aussehen. Ein Mittelwert aus 5 Verkäufen
ist etwas anderes als einer aus 228 — bei kleinen Fallzahlen können einzelne
Objekte den Stadtteilwert deutlich verschieben. Nenne die Fallzahl mit, wenn du
einen einzelnen Stadtteil zitierst.

## Indexreihen

Zwei qualitätsbereinigte Indizes, Basis 1.7.2010 = 100, jeweils 2015–2025:

- Eigentumswohnungen: Höchststand 300 (2022), 252 (2023/24), 265 (2025)
- Mehrfamilienhäuser: Höchststand 262 (2021), Tiefpunkt 175 (2024), 189 (2025)

Weil sie qualitätsbereinigt sind, folgen sie den rohen Mittelwerten nicht exakt.
Das ist kein Widerspruch, sondern der Zweck eines Index.

## Prüfung der Extraktion

Zwei unabhängige Kontrollen laufen gegen jeden textbasierten Jahrgang:

1. Gegenprobe gegen eine zweite, textbasierte Extraktion — null Wertabweichungen.
2. Summenprobe: die addierten Kauffälle je Stadtteil treffen exakt den im
   Bericht ausgewiesenen Gesamtwert. Ein übersehener Stadtteil würde die Summe
   zerstören.

Für 2025 greift keine von beiden: es gibt weder eine zweite Textquelle noch
Fallzahlen zum Aufsummieren. An ihre Stelle treten die Übereinstimmung zweier
Erkennungsmodelle und die Stichprobe von Hand.

## Wiesbaden

Bericht des Gutachterausschusses für Immobilienwerte Wiesbaden, frei abrufbar
unter einer Jahres-Adresse. 26 Stadtbezirke, Preisjahr 2025.

Wiesbaden trennt **drei Segmente**: Neubau (Erstverkauf), Umwandlung aus Miete
und Weiterverkauf. Damit liefert es die Bestand/Neubau-Aufteilung auf
Gebietsebene, die Hamburg nicht hergibt.

Die Tabellen stehen als Stadtbezirk × Baujahr × Wohnfläche; jede Zelle enthält
`Anzahl/Mittelpreis`. Der je Bezirk gezeigte Wert ist daraus **nach Kauffällen
gewichtet gerechnet**. Der Bericht gewichtet nach Fläche und nennt deshalb
leicht abweichende Gesamtwerte (etwa 3.842 statt 3.747 €/m² beim Weiterverkauf).
Wer Wiesbadener Zahlen zitiert, sollte das dazusagen.

Geprüft: die Fallzahlen aller drei Segmente treffen die Summenzeilen des
Berichts exakt — 150 (Neubau), 75 (Umwandlung), 979 (Weiterverkauf).

## Kiel

Bericht des Gutachterausschusses der Landeshauptstadt Kiel. Die Adressen wechseln
unregelmäßig, ein Jahresmuster gibt es nicht — das Skript liest die
Übersichtsseite und findet die aktuelle Ausgabe selbst.

26 Stadtteile, Preisjahr 2025. Stadtteilwerte führt Kiel **nur für
Weiterverkäufe**; Neubau und Umwandlung stehen dort ausschließlich
gesamtstädtisch. Je Stadtteil zusätzlich ausgewiesen: mittleres Baujahr und
mittlere Wohnfläche.

Der Gesamtwert für Kiel ist aus den Stadtteilen gewichtet gerechnet, nicht vom
Gutachterausschuss ausgewiesen.

Geprüft: null Abweichungen gegen den Rohtext der Stadtteiltabelle.

## Frankfurt am Main

Eingebunden, aber als einzige Stadt **ohne automatischen Abruf**. Die Stadt
schützt ihre Downloads mit einer JavaScript-Prüfung von Cloudflare; Bot-Schutz
wird nicht umgangen. Das Werkzeug versucht deshalb gar keinen Abruf, sondern
liest, was von Hand als `FFM<Jahr>.pdf` im Zwischenspeicher liegt:

```
~/.cache/immobilienmarktberichte/FFM2026.pdf
```

Liegt dort nichts, wird Frankfurt stillschweigend übersprungen — die übrigen
Städte sind davon nicht betroffen. Das ist der Normalfall auf einem frisch
eingerichteten Rechner: **die Berichte werden nicht mitgeliefert.**

Quelle ist Abschnitt 3.7.3 „Mittlere Preise für Eigentumswohnungen nach
Grundbuchbezirken". Besonderheiten, die in jede Antwort gehören:

- **Grundbuchbezirke statt Stadtteile.** 15 Gruppen, jede fasst mehrere
  Bezirke zusammen; die Ortsteilnamen stehen in Klammern dahinter. „Nordend,
  Ostend" ist ein Gebiet, nicht zwei.
- **Die Gebietswerte sind gerechnet, nicht abgelesen.** Der Bericht führt je
  Gebiet sechs Baujahrsklassen mit Anzahl und Preis; daraus wird nach
  Kauffällen gewichtet. Einen ausgewiesenen Gesamtwert je Gebiet gibt es nicht.
- **Drei Segmente:** Bestand (alle Klassen außer Neubau), Neubau, und Altbau
  (Baujahr bis 1918). Neubau hat nur in 7 der 15 Gebiete Werte.
- **Zwei Jahrgänge je Bericht.** Vier Berichte (2023–2026) ergeben die Reihe
  2021–2025, umschaltbar über Jahres-Reiter wie bei Hamburg. Überschneiden sich
  zwei Berichte in einem Jahr, gilt der neuere — er enthält die nachträglich
  korrigierten Zahlen.
- **Die Balkenskala gilt über alle Jahrgänge**, nicht je Jahr. Ein kürzerer
  Balken bedeutet also wirklich einen niedrigeren Preis, nicht bloß eine andere
  Skalierung.
- Der Bericht mahnt selbst zur Vorsicht bei kleinen Fallzahlen — einzelne
  Gebiete stützen sich auf unter zehn Verkäufe.

## Städte vergleichen

Vorsicht. Die Gutachterausschüsse grenzen unterschiedlich ab: Hamburg zählt
Stadtteile, Wiesbaden Stadtbezirke, Kiel statistische Stadtteile. Auch die
Segmente unterscheiden sich — Hamburg schließt Neubau aus, Wiesbaden weist ihn
getrennt aus. Innerhalb einer Stadt sind Vergleiche belastbar, zwischen Städten
nur mit Einordnung.

## Eine weitere Stadt ergänzen

Es gibt zwei Wege; welcher passt, entscheidet der Aufbau des Berichts.

- **Eintrag in `SOURCES`** in `scripts/imb.py` — URL-Muster, Bezeichnung der
  Gebietseinheit und die Überschriften der Tabellen. Setzt voraus, dass der
  Bericht unter einer nach Jahr aufgebauten Adresse liegt *und* seine Tabellen
  wie die Hamburger aufgebaut sind: Gebiet links, Wert rechtsbündig.
- **Eigener Leser in `scripts/staedte.py`** — der Regelfall. So sind Wiesbaden
  und Kiel eingebunden. Die Berichte sind strukturell verschieden; gemeinsam ist
  nur das Ausgabeformat `CityDataset`.
