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

Hamburg gesamt: 6.164 → 6.473 → 5.706 → 5.696 → 5.808 €/m².

Gesamtstädtisch zusätzlich: Preisindizes ETW und MFH (2015–2025), Kaufpreise
nach Baujahr × Lagequalität, Standardwohnung Bestand gegen Neubau.

## Getroffene Entscheidungen

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

**Colliers nur als Platzhalter.** Colliers veröffentlicht keine frei abrufbaren
Hamburg-Zahlen; der Report liegt hinter einem Anfrageformular. Zweiter Platzhalter
ist vdpResearch — transaktionsbasiert und damit belastbarer als Portalzahlen.

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

**Marktplatz ohne feste Versionsnummer.** Claude Code nimmt dann den Commit-Stand
als Version — jeder Push gilt als neue Fassung, kein Hochzählen nötig.

**`autoUpdate: true` in `~/.claude/settings.json`.** Eigene Marktplätze haben die
automatische Aktualisierung standardmäßig *aus*; das war der Grund, warum nie
etwas von allein ankam.

**Repository öffentlich.** Löst Zugriffs- und Aktualisierungsfragen. Inhaltlich
unkritisch, solange in `maklerdaten.json` nur öffentliche Quellenangaben stehen.

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

## Offene Punkte

**Kauffälle 2025 unvollständig.** Die Texterkennung überspringt auf der
Kauffälle-Seite rund fünf kleine Zahlen; Summe 5.479 statt ausgewiesener 5.543.
Die Preise sind davon nicht betroffen. Für 2025 fehlen deshalb die Fallzahlen je
Stadtteil — im Tooltip bleibt das Feld leer.

**Frankfurt fehlt.** Cloudflare-Prüfung beim Download; Bot-Schutz wird nicht
umgangen. Machbar wäre nur der Weg über ein von Hand geladenes PDF mit `--pdf`.
Ungeprüft ist, ob der Frankfurter Bericht überhaupt Stadtteiltabellen führt.

**Automatische Aktualisierung noch nicht bewiesen.** Einstellungen sind gesetzt
und die Dokumentation ist eindeutig, aber die Prüfung läuft mit bis zu zehn
Minuten Verzögerung nach Sitzungsstart. Beim nächsten Start eines Kollegen sollte
sich zeigen, ob die neue Fassung von allein ankommt.

**Wiesbaden und Kiel haben nur einen Jahrgang.** Die Verlaufsansicht ist dort
entsprechend dünn. Ältere Ausgaben liegen bei Wiesbaden unter derselben Adresse
(2025 abrufbar), bei Kiel auf der Übersichtsseite bis 2020.

**MFH-Lagetabellen aus Hamburg ungenutzt.** Abschnitt 2.3.4 und 2.3.5 führen
Preise und Ertragsfaktoren nach Lagequalität. Die Zahlen stehen aufrecht und sind
lesbar, nur die Zeilenbeschriftungen sind gedreht. Wäre mit überschaubarem
Aufwand nachzuholen.

**Colliers und vdpResearch ohne Zahlen.** Platzhalter stehen in
`maklerdaten.json`. Sobald der Report vorliegt, dort eintragen.

**Falls der Gutachterausschuss das PDF korrigiert**, wird die Texterkennung für
Hamburg 2025 überflüssig — dann greift der normale Textweg wieder von selbst.
Eine Anfrage dort wäre der sauberste Weg, das Problem dauerhaft loszuwerden.
