# Marktdaten Wohnen

Amtliche Immobilienmarktberichte des Gutachterausschusses abrufen, Kaufpreise je
Stadtteil auswerten und als interaktive Seite darstellen.

## Was es kann

Sag Claude zum Beispiel:

- „Starte eine neue Abfrage der Marktdaten"
- „Zeig mir die Kaufpreise nach Stadtteil"
- „Was kosten Eigentumswohnungen in Eppendorf?"
- „Wie haben sich die Preise seit 2021 entwickelt?"
- „Aktualisiere die Immobilienpreise"

Das Ergebnis ist eine eigenständige HTML-Seite mit:

- Kaufpreisen je Gebiet, absteigend sortiert, mit Favoriten und Suche — in
  **jeder** Stadt, Favoriten je Stadt getrennt gespeichert
- Verlaufsansicht über alle Jahrgänge mit Preisspanne je Gebiet, für Hamburg
  und Frankfurt
- Kaufpreisen nach Baujahr und Lagequalität als Farbmatrix
- Bestand gegen Neubau über die normierte Standardwohnung
- Preisindizes für Eigentumswohnungen und Mehrfamilienhäuser
- Mehrfamilienhäusern: Verkäufe je Stadtteil, Index, Stadtteilfaktoren

Die Datei ist eigenständig und lässt sich weitergeben — sie braucht weder Server
noch Internet.

## Voraussetzungen

Python 3.10 oder neuer. Alles Weitere richtet das Plugin beim ersten Aufruf
selbst ein; das dauert einmalig etwa eine Minute.

**Berichte werden nicht mehr geladen.** Die Zahlen liegen in einer
mitgelieferten Datenbank — der erste Lauf ist in Sekunden fertig, ohne Internet
und ohne 70 MB Download. Nur wer nach neuen Berichten sehen will, ruft sie mit
`--aktualisieren` ab.

## Wie die Datenbank arbeitet

Jeder Bericht wird einmal ausgelesen und eingelagert. Wiedererkannt wird er am
Hash seiner Datei: veröffentlicht ein Gutachterausschuss dieselbe Ausgabe
korrigiert neu, wird sie erneut gelesen, sonst nicht.

Jeder Wert trägt mit, aus welchem Bericht er stammt. Ändert ein späterer
Bericht einen alten Jahrgang — was regelmäßig passiert —, stehen beide Werte
nebeneinander. Angezeigt wird der neuere; `--korrekturen <stadt>` zeigt, was
sich bewegt hat.

| Befehl | Wirkung |
|---|---|
| (ohne) | Seite aus der Datenbank bauen |
| `--aktualisieren` | nach neuen Berichten sehen und einlagern |
| `--bestand` | zeigen, was gespeichert ist |
| `--korrekturen <stadt>` | nachträglich geänderte Werte auflisten |
| `--veroeffentlichen` | eigene Datenbank ins Plugin zurückschreiben |

## Datengrundlage

Grundlage sind **notariell beurkundete Kaufverträge**, nicht Angebotspreise.
Das ist der belastbarste verfügbare Datensatz für tatsächlich gezahlte Preise.

Abgedeckt sind drei Städte:

| Stadt | Gebiete | Segmente | Preisjahr |
|---|---|---|---|
| Hamburg | 104 Stadtteile | Bestand (ohne Neubau) | 2021–2025 |
| Wiesbaden | 26 Stadtbezirke | Neubau, Umwandlung, Weiterverkauf | 2025 |
| Kiel | 26 Stadtteile | Weiterverkauf | 2025 |
| Frankfurt am Main | 15 Grundbuchbezirke | Bestand, Neubau, Altbau | 2021–2025 |

Oben in der Seite schaltet man zwischen den Städten um.

**Frankfurt ist vollständig enthalten**, obwohl die Stadt automatisierte
Downloads sperrt: Ihre Berichte wurden einmal von Hand ausgewertet und liegen
seither in der Datenbank wie alle anderen Zahlen auch. Für einen **neuen**
Frankfurter Jahrgang legt man das PDF als
`~/.cache/immobilienmarktberichte/FFM<Jahr>.pdf` ab und ruft `--aktualisieren`
auf. Vier Berichte (2023–2026) ergeben die Reihe 2021–2025, weil jeder zwei
Jahrgänge führt.

Wichtige Grenzen: Für Neubau gibt es keine Werte je Stadtteil, für
Mehrfamilienhäuser keine Quadratmeterpreise je Stadtteil, und Stadtteile mit
weniger als drei Kauffällen bleiben ohne Angabe. Das Plugin benennt das jeweils,
statt zu schätzen.

## Zahlen Dritter

Zahlen aus Marktberichten Dritter — etwa Colliers oder vdpResearch — werden von
Hand gepflegt, in

```
~/.config/marktdaten-wohnen/quellen.json
```

Die Datei wird beim ersten Lauf aus der Vorlage im Plugin angelegt und liegt
bewusst **ausserhalb** des Plugins: `claude plugin update` ersetzt das
Plugin-Verzeichnis, eigene Einträge wären sonst weg. Ein anderer Ort geht mit
`--daten <pfad>`.

Diese Zahlen erscheinen in einem eigenen, abgesetzten Abschnitt und werden nie
mit den amtlichen Werten verrechnet. Jeder Eintrag führt seine Datengrundlage
mit — `Angebotspreis` misst Inserate, `Transaktionspreis` misst Abschlüsse — und
über `seite` und `erfasst` bleibt nachvollziehbar, woher der Wert stammt.

Die Prozentabweichung wird nur dort ausgewiesen, wo ein amtlicher Wert desselben
Gebiets vorliegt. Eine Frankfurter Zahl steht deshalb ohne Vergleich — das ist
gewollt und besser als ein Vergleich mit der falschen Stadt.
