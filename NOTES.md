# Arbeitsnotizen — Marktdaten Wohnen

Stand: 25. August 2026. Festgehalten sind der aktuelle Zustand, die getroffenen
Entscheidungen mit ihrer Begründung und die offenen Punkte. Gedacht als
Übergabe: wer hier weiterarbeitet, soll nicht dieselben Sackgassen nochmal
laufen müssen.

## Zustand

Ein Ordner, der zugleich Werkzeug, Plugin und Verteilungs-Marktplatz ist.
Alles gepusht nach `github.com/jbeight26/Marktdaten-Wohnen` (öffentlich).

```
Auswertung erstellen.command     Doppelklick → Auswertungen/marktdaten-wohnen.html
Interaktiv starten.command       lokaler Server, Knopf „Neue Abfrage" funktioniert
ANLEITUNG.html                   für Kollegen, auch als Artifact veröffentlicht
plugins/marktdaten-wohnen/       das Plugin, einzige Kopie aller Skripte
  scripts/imb.py                 Hauptskript, Hamburg + Orchestrierung
  scripts/staedte.py             Wiesbaden und Kiel
  scripts/ocr.py                 Texterkennung als Notnagel
  skills/…/SKILL.md              Anweisung für Claude
  skills/…/references/datenlage.md   Grenzen der Daten, wird bei Bedarf gelesen
```

### Datenabdeckung

| Stadt | Gebiete | Preisjahre | Herkunft |
|---|---|---|---|
| Hamburg | 104 Stadtteile | 2021–2024 | Text aus dem PDF |
| Hamburg | 104 Stadtteile | 2025 | **Texterkennung** |
| Wiesbaden | 26 Stadtbezirke | 2025 | Text, drei Segmente |
| Kiel | 26 Stadtteile | 2025 | Text, nur Weiterverkauf |
| Frankfurt | 15 Grundbuchbezirke | 2021–2025 | Text, von Hand abgelegte PDFs |

Hamburg gesamt: 6.164 → 6.473 → 5.706 → 5.696 → 5.808 €/m².

Gesamtstädtisch zusätzlich: Preisindizes ETW und MFH (2015–2025), Kaufpreise
nach Baujahr × Lagequalität, Standardwohnung Bestand gegen Neubau.

## Getroffene Entscheidungen

### Der Speicher

**Einmal auslesen, dauerhaft behalten.** Vorher wurde bei jedem Lauf jedes PDF
neu geparst. Jetzt liegen die Zahlen in SQLite; die Berichte werden nur noch
angefasst, wenn `--aktualisieren` läuft. Das löst vier Dinge auf einmal: kein
70-MB-Download beim Einrichten, kein Internet nötig, Frankfurt ohne von Hand
abgelegte PDFs — und alte Jahrgänge bleiben erhalten, auch wenn Hamburg sie von
daten-hamburg.de nimmt.

**SQLite, nicht Excel.** `sqlite3` steckt in Pythons Standardbibliothek; das
Plugin bleibt ohne zusätzliche Abhängigkeit installierbar. Excel wäre als
Wahrheitsquelle auch das falsche Format — als Export jederzeit machbar.

**Eine Zeile ist ein Faktum.** Ein einziges Schema trägt Hamburgs
Stadtteilpreise, Wiesbadens Segmente, Kiels Weiterverkäufe, Frankfurts
Grundbuchbezirke und die Zahlen Dritter. Eine neue Quelle braucht kein neues
Schema, nur einen Leser, der Fakten dieser Form liefert.

**Die Berichtsnummer steht im Schlüssel.** Damit ergibt derselbe Wert aus zwei
Berichten zwei Zeilen statt einer. Der Grund ist nicht Ordnungsliebe: die
Gutachterausschüsse **korrigieren alte Jahrgänge nachträglich**. Für Frankfurt
2024 weichen elf von fünfzehn Gebieten zwischen Bericht 2025 und 2026 ab, für
2023 neun von fünfzehn. Angezeigt wird der neuere Wert, `--korrekturen` zeigt
die Bewegung. Vorher wurde die alte Zahl still überschrieben.

**Zwei Dateien, kein Verdecken.** Die mitgelieferte Datenbank im Plugin ist der
Stand für alle; die Arbeitskopie unter `~/.local/share/marktdaten-wohnen`
überlebt Aktualisierungen. Bei jedem Start wandert Fehlendes aus der ersten in
die zweite — `INSERT OR IGNORE`, eigene Einträge bleiben unangetastet. Das ist
die Antwort auf das Verdeckungsproblem, das bei `quellen.json` noch offen war.

**Die Ausgabe kommt immer aus der Datenbank**, auch direkt nach einem
Auswertungslauf. Sonst könnte ein frischer Lauf etwas anderes zeigen als der
nächste. Belegt: nach dem Umbau war die erzeugte JSON-Datei Zeichen für Zeichen
identisch mit der vorherigen.

**Die Leser blieben unangetastet**, und die 1.300 Zeilen Darstellungscode
ebenso. Der Umbau sitzt in zwei neuen Dateien -- `db.py` für den Speicher,
`ablage.py` für den Weg hinein und heraus.

### Aufbau

**Ein Ordner statt zwei.** Vorher lagen Projektordner und Repository nebeneinander,
mit doppelten Skripten — das war die eigentliche Unordnung. Jetzt gibt es jede
Datei einmal, im Plugin. Die Starter im Stamm rufen sie von dort auf.

**Ordnername bleibt `marktdaten-wohnen-marketplace`.** Unschön, aber GitHub Desktop
merkt sich den Pfad; Umbenennen würde die Verknüpfung lösen.

**PDF-Zwischenspeicher unter `~/.cache/immobilienmarktberichte`, virtuelle Umgebung
unter `~/.venvs/marktdaten-wohnen`** — beides bewusst außerhalb von Google Drive.
Gemessen: PDF-Parsen direkt vom Drive-Laufwerk dauerte Minuten, lokal 0,2 s. Beim
ersten Plugin-Start brauchte Drive zwei Minuten, nur um die Bibliotheken zu laden.

### Auswertung

**Koordinatenbasiertes Parsen statt Zeilentext.** Die Tabellen haben keine Linien,
sondern mehrere Spaltenpaare nebeneinander. Werte sitzen rund 3 pt höher als die
Namen und gehören trotzdem in dieselbe Zeile.

**Wertespalten eng clustern.** Ein einzelnes Fußzeilen-Token zog sonst die
Spaltengrenze über die Namen der Nachbarspalte — kostete in IMB2024 zunächst 35
Stadtteile.

**Seite mit der höchsten Ausbeute gewinnt, nicht der erste Überschriftentreffer.**
Der Bericht setzt Doppelseiten; die Nachbarseite trägt dieselbe Tabelle mit
negativen x-Koordinaten.

**Seitenindex und Ringsuche.** Der Seiten-Scan ist zu 99 % die Laufzeit (190–330 ms
je Seite). Ringsuche um einen Erwartungswert und ein gemerkter Index bringen
Folgeläufe von 81 s auf 1,3 s.

**Je Stadt ein eigener Tabellenleser.** Die Berichte sind strukturell verschieden:
Hamburg Gebiet → Wert, Wiesbaden Bezirk × Baujahr × Wohnfläche mit `Anzahl/Preis`
je Zelle, Kiel eine schlichte Zeilentabelle. Ein gemeinsamer Parser wäre eine
Zwangsjacke gewesen.

**Gemeinsame Skala über alle Jahrgänge.** Bei Neuskalierung je Jahr sähen die
Balken jedes Jahr gleich lang aus und die Preisentwicklung verschwände.

### Ehrlichkeit der Zahlen

**Maklerzahlen bleiben getrennt** und werden nie mit den amtlichen verrechnet.
Grund: die Kaufpreissammlung erfasst gesetzlich verpflichtend jeden beurkundeten
Verkauf, Maklerberichte zeigen Inserate oder das eigene Portfolio. Jeder Eintrag
führt seine Datengrundlage sichtbar mit.

**Colliers ist eingepflegt — aber nicht als das, was erwartet war.** Der Report
„Wohnungsmarkt Deutschland 2025/2026“ liegt vor und ist ausgewertet. Entscheidend:
er enthält **keine Eigentumswohnungspreise**. Das Wort kommt auf 79 Seiten kein
einziges Mal vor. Was er je Stadt führt, sind Mieten und — unter „Wohn- &
Geschäftshäuser“ — Kaufpreisfaktoren und Quadratmeterpreise, gegliedert nach
Lagequalität statt nach Gebiet.

Übernommen sind die €/m²-Spannen für Hamburg (S.46), Frankfurt (S.41), Kiel
(S.53) und Wiesbaden (S.75), ausgezeichnet als Objektart „Wohn- und
Geschäftshäuser“. Sie mit den amtlichen ETW-Preisen zu vergleichen wäre ein
Kategorienfehler; die Auswertung verhindert das, indem sie für die Ebene „lage“
und für Spannen grundsätzlich keine Prozentabweichung rechnet. Die
Kaufpreisfaktoren stehen auf denselben Seiten und sind noch nicht übernommen.

Zweiter Platzhalter bleibt vdpResearch — transaktionsbasiert und damit belastbarer
als Portalzahlen.

**Wiesbadens Bezirkswerte sind gerechnet, nicht abgelesen** (nach Kauffällen
gewichtet aus den Zellen). Der Bericht gewichtet nach Fläche und nennt deshalb
leicht andere Gesamtwerte — 3.842 gegen unsere 3.747 €/m². Steht als Hinweis
unter dem Diagramm.

**Bestand/Neubau je Stadtteil gibt es für Hamburg nicht.** Die Stadtteiltabelle
ist ausdrücklich „ohne Neubau". Die Auswertung sagt das offen, statt eine leere
Ansicht zu zeigen. Wiesbaden liefert die Trennung dagegen auf Gebietsebene.

**Texterkennung nur mit doppelter Absicherung.** Zwei Erkennungsmodelle müssen in
jedem Wert übereinstimmen, sonst kein Ergebnis. Abgeglichen wird über die
Position, nicht über den Namen: das schnelle Modell liest Ziffern zuverlässig,
verstümmelt aber Umlaute („Allermohe"). Zusätzlich wurden 19 Werte von Hand am
Bild gegengeprüft, ohne Abweichung.

### Verteilung

**Marktplatz ohne feste Versionsnummer — das gilt aber nur für den
Marktplatz-Eintrag.** Die `version` in `plugins/marktdaten-wohnen/.claude-plugin/plugin.json`
ist sehr wohl tragend: Claude Code legt die heruntergeladene Fassung unter
`~/.claude/plugins/cache/eight-estates/marktdaten-wohnen/<version>/` ab und
schreibt Version *und* Commit-SHA nach `installed_plugins.json`. Die Annahme,
Pushes allein genügten, war falsch — **jede Veröffentlichung braucht ein
Hochzählen in plugin.json**.

**`autoUpdate: true` in `~/.claude/settings.json`.** Eigene Marktplätze haben die
automatische Aktualisierung standardmäßig *aus*; das war der Grund, warum nie
etwas von allein ankam.

**Zusatzstädte können jetzt mehrere Jahrgänge führen.** `CityDataset` hat eine
Liste von `CityYear`; `segments` und `data_year` zeigen weiter auf das neueste
Jahr, damit einjährige Städte unverändert funktionieren. Wiesbaden und Kiel
bekommen keine Jahres-Reiter — ein einzelner Reiter wäre eine Schaltfläche ohne
Wahl.

**Verlauf und Favoriten in allen Städten.** Die Zusatzstädte hatten weder das
eine noch das andere — die Leitstadt-Ansicht und `renderCity` waren getrennt
gewachsen. Beides ist jetzt portiert: ein Reiter „Verlauf“ neben den Jahren
(nur wo es mehrere gibt), Sterne in jeder Zeile, Suchfeld und
Nur-Favoriten-Schalter.

**Favoriten liegen je Stadt getrennt** unter `imb-favoriten-<stadt>`. Eppendorf
und Westend gehören nicht in dieselbe Liste. Der Schlüssel folgt der aktiven
Stadt; beim Umschalten wird die Liste der neuen Stadt geladen. Zu beachten:
`loadFavs()` läuft schon während der Erzeugung von `state`, deshalb muss
`favKey()` ein noch leeres `state` aushalten.

**Gemeinsame Skala auch bei den Zusatzstädten.** Der längste Balken bemisst sich
über alle Jahrgänge des gewählten Segments, nicht über das gezeigte Jahr.
Dieselbe Entscheidung wie bei Hamburg, aus demselben Grund: sonst sieht jedes
Jahr gleich aus. Sichtbar wird das am Westend, das von 10.116 auf 8.166 €/m²
fällt — der Balken schrumpft von 81 % auf 65 % der Breite.

**Repository öffentlich.** Löst Zugriffs- und Aktualisierungsfragen. Inhaltlich
unkritisch, solange dort nur öffentliche Quellenangaben stehen.

**Selbst gepflegte Zahlen liegen ausserhalb des Plugins**, in
`~/.config/marktdaten-wohnen/quellen.json`. Grund: `claude plugin update`
ersetzt das Plugin-Verzeichnis vollständig — eine im Plugin gepflegte Datei wäre
nach der nächsten Aktualisierung weg. Die Datei im Plugin ist nur noch Vorlage
und wird beim ersten Lauf einmalig kopiert. Suchreihenfolge: `--daten`, dann
`MARKTDATEN_QUELLEN`, dann die Nutzerdatei.

**Abweichungen nur gegen dasselbe Gebiet.** Fremdzahlen werden gegen den
amtlichen Wert *derselben* Stadt gerechnet, bei `"ebene": "stadtteil"` gegen den
Wert desselben Stadtteils. Gibt es keinen passenden amtlichen Wert — etwa bei
Frankfurt —, zeigt die Seite bewusst keine Prozentzahl. Vorher lief jede
Abweichung gegen den Hamburger Gesamtwert; das wäre beim ersten
Nicht-Hamburg-Eintrag still zu einer falschen Zahl geworden.

## Fallstricke, die Zeit gekostet haben

- **`claude plugin install` aktualisiert nicht.** Es meldet „ist bereits
  installiert". Es muss `claude plugin update` sein.
- **`/plugin` gibt es in der Desktop-App nicht.** Nur im Terminal mit `claude`.
- **IMB2026 hat die Tabellen nicht entfernt** — die Schrift ist dort in
  Vektorkonturen umgewandelt, 32 der 214 Seiten. Seite 44: 1.845 Textzeichen in
  2025 gegen 38 in 2026 bei 2.546 Kurvenobjekten. Ich hatte das zunächst als
  Umbau des Berichts fehlgedeutet; das steht so nicht mehr in der Doku.
- **Ein gemerkter Negativeintrag im Seitenindex blockierte die Texterkennung.**
  Behoben: bei der Leittabelle wird OCR auch dann versucht.
- **Google Drive kann Lesezugriffe minutenlang blockieren**, während es synct.
  Deshalb liegt alles Rechenintensive außerhalb.
- **Eine Sperrseite kann als PDF im Zwischenspeicher landen.** Im Cache lag eine
  `FFM2026.pdf` mit 6 KB — die Cloudflare-Seite „Just a moment…“, gespeichert
  unter PDF-Namen. `download_pdf` prüft inzwischen auf `%PDF` und schreibt so
  etwas nicht mehr; der Zwischenspeicher-Treffer und `--pdf` prüften aber weiter
  ungefragt. Beides prüft jetzt den Dateikopf, sonst fällt der Fehler erst beim
  Parsen als kryptische pdfminer-Meldung auf.

## Offene Punkte

**Kauffälle 2025 unvollständig.** Die Texterkennung überspringt auf der
Kauffälle-Seite rund fünf kleine Zahlen; Summe 5.479 statt ausgewiesener 5.543.
Die Preise sind davon nicht betroffen. Für 2025 fehlen deshalb die Fallzahlen je
Stadtteil — im Tooltip bleibt das Feld leer.

**Frankfurt braucht keine PDFs mehr.** Die Berichte wurden einmal ausgewertet;
seither kommen die Zahlen aus der Datenbank wie bei jeder anderen Stadt. Nur
ein *neuer* Jahrgang verlangt noch das PDF im Zwischenspeicher.

**Frankfurt ist drin.** Die lange offene Frage ist beantwortet: der Bericht
führt Gebietstabellen, in Abschnitt 3.7.3 „Mittlere Preise für
Eigentumswohnungen nach Grundbuchbezirken“. Damit war der Rest Handwerk.

Aufbau: 15 Gruppen von Grundbuchbezirken, je Gruppe **zwei** Jahrgänge, je
Jahrgang sechs Baujahrsklassen mit Anzahl und Preis. Vier Berichte (2023–2026)
ergeben deshalb die Reihe 2021–2025 — dieselbe Spanne wie Hamburg, mit
Jahres-Reitern wie dort. Bei Überschneidung gewinnt der neuere Bericht: er
enthält die nachträglich korrigierten Zahlen.

Drei Entscheidungen dazu:

- **Kein Download-Versuch.** Cloudflare sperrt, Bot-Schutz wird nicht umgangen.
  Der Leser liest ausschließlich, was als `FFM<Jahr>.pdf` im Zwischenspeicher
  liegt. Fehlt alles, wird Frankfurt übersprungen — kein Fehler, nur ein Reiter
  weniger. Auf einem frisch eingerichteten Rechner ist das der Normalfall.
- **Die Berichte liegen nicht im Repository.** Es sind rund 11 MB fremdes
  Material; verteilt wird der Leser, nicht die Quelle.
- **Gebietswerte werden gerechnet**, nach Kauffällen gewichtet über die
  Baujahrszellen — der Bericht weist je Gebiet keinen Gesamtwert aus. Dieselbe
  Entscheidung wie bei Wiesbaden, aus demselben Grund.

Gegenprobe: Westend 2025 ergibt 677.740 / 83 = 8.166 €/m². Der Bericht nennt im
Fließtext Bornheim als teuersten Neubau mit „rund 9.600 €/m²“ — der Leser
liefert dort 9.630 €/m².

**Automatische Aktualisierung kommt nicht an — Befund vom 25.08.2026.** Nicht
mehr „unbewiesen“, sondern nachweislich hängend. Auf diesem Rechner:

- `installed_plugins.json` führt weiterhin **1.1.0**, Commit `b35b71e`,
  zuletzt aktualisiert am 24.08. um 14:52. Das ist der Stand *vor* der
  Texterkennung — dieser Rechner arbeitet im Plugin also mit altem Code.
- Der Marktplatz-Klon dagegen ist aktuell (`0420e6f`, 25.08. um 10:09). Die
  Marktplatz-Aktualisierung funktioniert also.
- Im Cache liegt **1.2.0 bereits vollständig** (geladen 25.08. um 12:09), trägt
  aber `.orphaned_at` (12:20) und kein `.in_use`. Die Fassung wurde geholt, aber
  nie aktiv geschaltet, und wurde dann als verwaist markiert.

Heruntergeladen wird also, umgeschaltet nicht. Nächster Schritt: im Terminal
`claude plugin update marktdaten-wohnen@eight-estates` ausführen und danach
`installed_plugins.json` erneut ansehen. Zieht der Zeiger dort auf die neue
Version, liegt es allein am automatischen Umschalten; bleibt er stehen, stimmt
etwas mit dem Marktplatz-Eintrag nicht.

**Wiesbaden und Kiel haben nur einen Jahrgang.** Die Verlaufsansicht ist dort
entsprechend dünn. Ältere Ausgaben liegen bei Wiesbaden unter derselben Adresse
(2025 abrufbar), bei Kiel auf der Übersichtsseite bis 2020.

**Drei fast gleiche Blöcke in `collect_cities`.** Mit Frankfurt sind es jetzt
drei; eine Registry (Schlüssel → Abrufer/Auswerter) wäre überfällig. Bewusst
nicht mitgemacht, um die Änderung klein zu halten.

**Colliers-Kaufpreisfaktoren ungenutzt.** Stehen je Stadt und Lagequalität auf
denselben Seiten wie die übernommenen Preise. Gleiche Struktur, andere Einheit —
mit dem jetzigen Schema ein reiner Dateneintrag, kein Codeaufwand.

**MFH-Lagetabellen aus Hamburg ungenutzt.** Abschnitt 2.3.4 und 2.3.5 führen
Preise und Ertragsfaktoren nach Lagequalität. Die Zahlen stehen aufrecht und sind
lesbar, nur die Zeilenbeschriftungen sind gedreht. Wäre mit überschaubarem
Aufwand nachzuholen.

**vdpResearch ohne Zahlen.** Platzhalter in
`~/.config/marktdaten-wohnen/quellen.json` (Vorlage im Plugin). Beim Eintragen
`seite` und `erfasst` setzen, damit am Wert selbst ablesbar bleibt, woher er
stammt und wer ihn geprüft hat.

**Eigentumswohnungspreise Dritter fehlen weiterhin.** Colliers liefert sie nicht
(siehe oben). Für den Quervergleich zu den amtlichen ETW-Preisen bräuchte es eine
andere Quelle; vdpResearch wäre der nächste Kandidat.

**Die Nutzerdatei verdeckt die Vorlage dauerhaft.** Wer einmal
`quellen.json` hat, bekommt spätere Ergänzungen aus dem Plugin nicht mehr —
die eigene Datei gewinnt immer. Für die Colliers-Zahlen ist das umgangen, indem
sie in **beiden** Dateien stehen. Auf Dauer bräuchte es ein Zusammenführen
(Vorlage als Grundstock, Nutzerdatei nur als Ergänzung) statt eines
Entweder-oder. Vor der nächsten verteilten Datenpflege zu klären.

**Falls der Gutachterausschuss das PDF korrigiert**, wird die Texterkennung für
Hamburg 2025 überflüssig — dann greift der normale Textweg wieder von selbst.
Eine Anfrage dort wäre der sauberste Weg, das Problem dauerhaft loszuwerden.
