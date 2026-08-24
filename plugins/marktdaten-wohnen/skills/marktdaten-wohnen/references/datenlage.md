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

**Aus IMB2026 lassen sich die Stadtteilwerte nicht auslesen.** Die Tabellen
stehen dort im Bericht, auf denselben Seiten wie im Vorjahr, sind aber als
Vektorkonturen gesetzt statt als Text — 32 der 214 Seiten sind so gesetzt,
im Vorjahr war es eine. Seite 44 enthält 2025 noch 1.845 Textzeichen bei 60
Kurvenobjekten, 2026 nur 38 Textzeichen bei 2.546 Kurven.

Sage das, wenn jemand nach dem fehlenden Jahr fragt, und sage auch, dass
`--page` hier nicht hilft: es gibt keinen Text zum Auslesen. Nötig wäre OCR
oder eine Anfrage beim Gutachterausschuss. Das Skript überspringt den Jahrgang
für die Stadtteilansicht, nutzt ihn aber für Lagematrix und Indexreihen —
darüber kommt das Preisjahr 2025 dennoch in die Auswertung.

Damit umfasst die Stadtteilreihe die Preisjahre **2021 bis 2024**.

## Was es je Stadtteil gibt

| Angabe | Eigentumswohnungen | Mehrfamilienhäuser |
|---|---|---|
| Kaufpreis €/m² | ja, 2021–2024 | **nein** |
| Anzahl Kauffälle | ja | ja, als Verkaufszahlen |
| Stadtteilfaktor | ja | ja |

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

Zwei unabhängige Kontrollen laufen gegen jeden Jahrgang:

1. Gegenprobe gegen eine zweite, textbasierte Extraktion — null Wertabweichungen.
2. Summenprobe: die addierten Kauffälle je Stadtteil treffen exakt den im
   Bericht ausgewiesenen Gesamtwert. Ein übersehener Stadtteil würde die Summe
   zerstören.

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

## Frankfurt

**Nicht eingebunden.** Die Stadt schützt ihre Downloads mit einer
JavaScript-Prüfung von Cloudflare. Bot-Schutz wird nicht umgangen. Wer Frankfurt
braucht, lädt das PDF im Browser und übergibt es mit `--pdf`.

## Städte vergleichen

Vorsicht. Die Gutachterausschüsse grenzen unterschiedlich ab: Hamburg zählt
Stadtteile, Wiesbaden Stadtbezirke, Kiel statistische Stadtteile. Auch die
Segmente unterscheiden sich — Hamburg schließt Neubau aus, Wiesbaden weist ihn
getrennt aus. Innerhalb einer Stadt sind Vergleiche belastbar, zwischen Städten
nur mit Einordnung.

## Eine weitere Stadt ergänzen

Der Kern-Parser ist nicht stadtspezifisch. Eine weitere Stadt wird über einen Eintrag
in `SOURCES` in `scripts/imb.py` ergänzt: URL-Muster, Bezeichnung der
Gebietseinheit und die Überschriften der Tabellen. Voraussetzung ist, dass der
dortige Gutachterausschuss seinen Bericht als PDF unter einer nach Jahr
aufgebauten Adresse veröffentlicht.
