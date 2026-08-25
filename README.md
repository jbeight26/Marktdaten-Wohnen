# Marktdaten Wohnen

Amtliche Immobilienmarktberichte der Gutachterausschüsse auswerten und als
interaktive Seite darstellen. Hamburg, Wiesbaden, Kiel und Frankfurt am Main.

Dieser Ordner ist zugleich das Claude-Plugin, der Marktplatz zum Verteilen und
das Arbeitswerkzeug — alles an einer Stelle, jede Datei nur einmal.

Die Zahlen liegen in einer **mitgelieferten Datenbank**
(`plugins/marktdaten-wohnen/scripts/daten/marktdaten.db`). Jeder Bericht wird
einmal ausgelesen; danach braucht niemand mehr ein PDF. Das gilt auch für
Frankfurt, dessen Berichte sich nicht abrufen lassen.

Der Ablauf für neue Daten: `--aktualisieren` liest, was noch fehlt →
`--veroeffentlichen` schreibt es ins Plugin → committen und pushen.

## Ohne Kommandozeile benutzen

| Datei | Wirkung |
|---|---|
| `Auswertung erstellen.command` | sieht nach neuen Berichten, lagert sie ein, öffnet die Auswertung |
| `Datenbank veroeffentlichen.command` | schreibt die eigenen Zahlen ins Plugin, damit sie zu den Kollegen gehen |
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
  scripts/                           imb.py, staedte.py, ocr.py
  scripts/db.py, ablage.py           Datenspeicher und Ein-/Auslagern
  scripts/daten/marktdaten.db        die mitgelieferten Zahlen
  scripts/maklerdaten.json           Vorlage für Zahlen Dritter
~/.local/share/marktdaten-wohnen/    Arbeitsdatenbank, überlebt Aktualisierungen
~/.config/marktdaten-wohnen/         eigene Quellendatei, überlebt Aktualisierungen
Auswertungen/                        erzeugte Dateien (nicht im Repository)
```

## Abgedeckte Städte

| Stadt | Gebiete | Segmente | Preisjahre |
|---|---|---|---|
| Hamburg | 104 Stadtteile | Bestand (ohne Neubau) | 2021–2025 |
| Wiesbaden | 26 Stadtbezirke | Neubau, Umwandlung, Weiterverkauf | 2025 |
| Kiel | 26 Stadtteile | Weiterverkauf | 2025 |
| Frankfurt am Main | 15 Grundbuchbezirke | Bestand, Neubau, Altbau | 2021–2025 |

Frankfurt ist vollständig enthalten, obwohl die Stadt Downloads mit einer
Cloudflare-Prüfung sperrt: Die Berichte wurden einmal von Hand ausgewertet, die
Zahlen stehen seither in der Datenbank. Nur für einen **neuen** Jahrgang muss
das PDF als `~/.cache/immobilienmarktberichte/FFM<Jahr>.pdf` abgelegt werden;
die PDFs selbst sind nicht Teil des Repositorys.

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
