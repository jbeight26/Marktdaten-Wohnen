#!/bin/bash
# Doppelklick startet die Auswertung im Browser -- dort funktioniert
# der Knopf "Neue Abfrage" wirklich. Beenden: dieses Fenster schliessen.
cd "$(dirname "$0")" || exit 1

VENV="$HOME/.venvs/marktdaten-wohnen"
SKRIPT="plugins/marktdaten-wohnen/scripts/imb.py"

echo "==========================================="
echo "  Marktdaten Wohnen — live im Browser"
echo "==========================================="
echo

if [ ! -x "$VENV/bin/python" ]; then
  echo "Erster Start: die Arbeitsumgebung wird eingerichtet …"
  python3 -m venv "$VENV" \
    && "$VENV/bin/pip" install -q -r plugins/marktdaten-wohnen/scripts/requirements.txt \
    && "$VENV/bin/pip" install -q -r plugins/marktdaten-wohnen/scripts/requirements-ocr.txt 2>/dev/null
  echo "Eingerichtet."; echo
fi

echo "Der Browser öffnet sich gleich von selbst."
echo "Zum Beenden: dieses Fenster schliessen (Cmd+W)."
echo
( sleep 4; open "http://127.0.0.1:8000" ) &
"$VENV/bin/python" -u "$SKRIPT" --serve
