# Marktdaten Wohnen

Amtliche Immobilienmarktberichte der Gutachterausschüsse auswerten und als
interaktive Seite darstellen. Hamburg, Wiesbaden und Kiel.

Dieser Ordner ist zugleich das Claude-Plugin, der Marktplatz zum Verteilen und
das Arbeitswerkzeug — alles an einer Stelle, jede Datei nur einmal.

## Ohne Kommandozeile benutzen

| Datei | Wirkung |
|---|---|
| `Auswertung erstellen.command` | holt die Berichte, baut die Auswertung, öffnet sie |
| `Interaktiv starten.command` | startet den lokalen Server; dort funktioniert der Knopf „Neue Abfrage" |
| `ANLEITUNG.html` | Anleitung zum Weitergeben an Kollegen |

Ergebnisse landen in `Auswertungen/`. Die HTML-Datei ist eigenständig und lässt
sich weitergeben — sie braucht weder Server noch Internet.

## Als Plugin verteilen

```
/plugin marketplace add jbeight26/Marktdaten-Wohnen
/plugin install marktdaten-wohnen@eight-estates
```

Aktualisieren nach einer neuen Fassung — `install` genügt **nicht**:

```
claude plugin marketplace update eight-estates
claude plugin update marktdaten-wohnen@eight-estates
```

Danach Claude neu starten und mit `claude plugin list` prüfen, ob die Version
stimmt.

## Aufbau

```
.claude-plugin/marketplace.json      Katalog für die Verteilung
plugins/marktdaten-wohnen/
  .claude-plugin/plugin.json         Beschreibung des Plugins
  skills/marktdaten-wohnen/          Anweisung für Claude, samt Datenlage
  scripts/                           imb.py, staedte.py, ocr.py, maklerdaten.json
Auswertungen/                        erzeugte Dateien (nicht im Repository)
```

## Abgedeckte Städte

| Stadt | Gebiete | Segmente | Preisjahre |
|---|---|---|---|
| Hamburg | 104 Stadtteile | Bestand (ohne Neubau) | 2021–2025 |
| Wiesbaden | 26 Stadtbezirke | Neubau, Umwandlung, Weiterverkauf | 2025 |
| Kiel | 26 Stadtteile | Weiterverkauf | 2025 |

Frankfurt fehlt: die Stadt sperrt automatisierte Downloads mit einer
Cloudflare-Prüfung.

## Hamburg 2025 kommt aus einer Texterkennung

Der Bericht 2026 setzt seine Stadtteiltabellen als Grafik — 32 der 214 Seiten
sind in Vektorkonturen umgewandelt. Für ein Programm ist das ein Bild.

Das Werkzeug rendert die Seite und liest sie mit der Texterkennung von macOS,
**mit beiden Erkennungsmodellen**. Nur Werte, in denen beide übereinstimmen,
werden übernommen; bei Widerspruch bricht es lieber ab. Alle 104 Stadtteilnamen
wurden gefunden, 76 Werte doppelt bestätigt, und eine Stichprobe von 19 Werten
wurde zusätzlich von Hand am Bild gegengeprüft — ohne Abweichung.

Die Auswertung kennzeichnet diesen Jahrgang sichtbar. Verloren geht dabei die
Unterscheidung zwischen „*" (unter drei Kauffällen) und „–" (kein Wert).

Ohne die Zusatzpakete (`requirements-ocr.txt`, nur macOS) läuft alles Übrige
unverändert; dann fehlt lediglich Hamburg 2025. Mit `--no-ocr` lässt sich die
Texterkennung abschalten.
