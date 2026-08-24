# eight estates — Marktplatz für Claude-Plugins

Interne Werkzeuge für die Arbeit mit Immobilienmarktdaten.

## Einmalig einrichten

In Claude Code:

```
/plugin marketplace add <ORG>/<REPO>
/plugin install marktdaten-wohnen@eight-estates
```

`<ORG>/<REPO>` durch die Adresse dieses Repositories ersetzen. Liegt es nicht auf
GitHub, die vollständige URL angeben:

```
/plugin marketplace add https://gitlab.example.com/team/marktdaten-wohnen-marketplace.git
```

Meldet die Installation `Run /reload-plugins to activate.`, diesen Befehl noch
ausführen.

## Benutzen

Danach genügt eine normale Bitte an Claude:

- „Starte eine neue Abfrage der Marktdaten"
- „Zeig mir die Kaufpreise nach Stadtteil"
- „Was kosten Eigentumswohnungen in Eppendorf?"
- „Wie haben sich die Preise seit 2021 entwickelt?"

## Aktualisieren

Neue Fassungen kommen nicht von allein an. Nach einer Änderung im Repository:

```
/plugin marketplace update eight-estates
```

## Enthaltene Plugins

| Plugin | Zweck |
|---|---|
| `marktdaten-wohnen` | Immobilienmarktberichte des Gutachterausschusses auswerten und darstellen |

## Voraussetzungen

Python 3.10 oder neuer. Alles Weitere richtet das Plugin beim ersten Aufruf
selbst ein.

## Eine neue Fassung veröffentlichen

1. Änderungen unter `plugins/marktdaten-wohnen/` vornehmen
2. Versionsnummer in **beiden** Dateien erhöhen:
   `plugins/marktdaten-wohnen/.claude-plugin/plugin.json` und
   `.claude-plugin/marketplace.json`
3. Committen und pushen
4. Kollegen informieren, dass sie `/plugin marketplace update eight-estates`
   ausführen sollen

Weichen die beiden Versionsnummern voneinander ab, warnt die Prüfung.
