#!/bin/bash
# Schreibt die eigene Arbeitsdatenbank ins Plugin zurueck, damit die neuen
# Zahlen mit dem naechsten Push bei den Kollegen ankommen.
cd "$(dirname "$0")" || exit 1

VENV="$HOME/.venvs/marktdaten-wohnen"
SKRIPT="plugins/marktdaten-wohnen/scripts/imb.py"

echo "==========================================="
echo "  Marktdaten Wohnen — Datenbank freigeben"
echo "==========================================="
echo

if [ ! -x "$VENV/bin/python" ]; then
  echo "Die Arbeitsumgebung fehlt. Bitte zuerst „Auswertung erstellen“ starten."
  echo; echo "Fenster kann geschlossen werden (Cmd+W)."; exit 1
fi

"$VENV/bin/python" -u "$SKRIPT" --veroeffentlichen
echo
echo "Danach in GitHub Desktop committen und pushen."
echo "Erst dann sehen die Kollegen die neuen Zahlen."
echo
echo "Fenster kann geschlossen werden (Cmd+W)."
