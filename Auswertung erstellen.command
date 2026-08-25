#!/bin/bash
# Doppelklick genügt: holt die aktuellen Berichte und baut die Auswertung neu.
cd "$(dirname "$0")" || exit 1

VENV="$HOME/.venvs/marktdaten-wohnen"      # bewusst ausserhalb von Google Drive
SKRIPT="plugins/marktdaten-wohnen/scripts/imb.py"
ZIEL="Auswertungen/marktdaten-wohnen.html"

echo "==========================================="
echo "  Marktdaten Wohnen — Auswertung erstellen"
echo "==========================================="
echo

if [ ! -x "$VENV/bin/python" ]; then
  echo "Erster Start: die Arbeitsumgebung wird eingerichtet."
  echo "Das dauert etwa eine Minute und passiert nur dieses eine Mal …"
  echo
  python3 -m venv "$VENV" || { echo "Einrichtung fehlgeschlagen."; exit 1; }
  "$VENV/bin/pip" install -q -r plugins/marktdaten-wohnen/scripts/requirements.txt || {
    echo "Einrichtung fehlgeschlagen."; exit 1; }
  # Texterkennung: ohne sie fehlt der Jahrgang 2025 für Hamburg, weil dessen
  # Tabelle im Bericht als Grafik gesetzt ist. Fehler nicht verschlucken.
  echo "Richte die Texterkennung ein …"
  if ! "$VENV/bin/pip" install -q -r plugins/marktdaten-wohnen/scripts/requirements-ocr.txt; then
    echo "  Fehlgeschlagen — Hamburg 2025 bleibt dann leer, der Rest funktioniert."
  fi
  echo "Eingerichtet."
  echo
fi

echo "Berichte werden abgerufen. Bitte einen Moment warten …"
echo
"$VENV/bin/python" -u "$SKRIPT" --out "$ZIEL" --json "Auswertungen/marktdaten-wohnen.json"
status=$?

echo
if [ $status -eq 0 ]; then
  echo "Fertig. Die Auswertung wird jetzt geöffnet."
  open "$ZIEL"
else
  echo "Fehlgeschlagen. Der Text oben sagt, woran es lag."
  echo "Häufigster Fall: keine Internetverbindung."
fi
echo
echo "Fenster kann geschlossen werden (Cmd+W)."
