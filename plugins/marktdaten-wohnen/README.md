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

Der erste Lauf lädt rund 70 MB an PDF-Berichten und dauert etwa anderthalb
Minuten. Danach greift ein Zwischenspeicher unter `~/.cache/immobilienmarktberichte`
und die Auswertung ist in Sekunden fertig.

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

**Frankfurt braucht einen Handgriff.** Die Stadt sperrt automatisierte Downloads
mit einer Cloudflare-Prüfung, deshalb versucht das Werkzeug dort gar keinen
Abruf. Es liest, was von Hand abgelegt wurde:

```
~/.cache/immobilienmarktberichte/FFM<Jahr>.pdf
```

Die Berichte lädt man einmalig beim Frankfurter Gutachterausschuss und legt sie
dort ab — vier Berichte (2023–2026) ergeben die Reihe 2021–2025, weil jeder zwei
Jahrgänge führt. Liegt nichts da, wird Frankfurt übersprungen; die anderen Städte
funktionieren unverändert. **Die Berichte werden nicht mitgeliefert.**

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
