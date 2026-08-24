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

- Kaufpreisen je Stadtteil, absteigend sortiert, mit Favoriten und Suche
- Verlaufsansicht über alle Jahrgänge mit Preisspanne je Stadtteil
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

Aktuell hinterlegt: Hamburg, Preisjahre 2021 bis 2025. Weitere Städte lassen
sich über einen Eintrag in `scripts/imb.py` ergänzen.

Wichtige Grenzen: Für Neubau gibt es keine Werte je Stadtteil, für
Mehrfamilienhäuser keine Quadratmeterpreise je Stadtteil, und Stadtteile mit
weniger als drei Kauffällen bleiben ohne Angabe. Das Plugin benennt das jeweils,
statt zu schätzen.

## Zahlen Dritter

`scripts/maklerdaten.json` nimmt Zahlen aus Marktberichten Dritter auf. Sie
erscheinen in einem eigenen, abgesetzten Abschnitt und werden nie mit den
amtlichen Werten verrechnet. Jeder Eintrag führt seine Datengrundlage mit —
`Angebotspreis` misst Inserate, `Transaktionspreis` misst Abschlüsse.
