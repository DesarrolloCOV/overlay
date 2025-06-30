#!/bin/bash

qterminal -e bash -c '
journalctl -u overlay.service -f | while IFS= read -r line; do
  # Verde para [vantX]
  line=$(echo "$line" | sed -E "s/(\\[vant[0-9]+\\])/\\x1b[1;32m\\1\\x1b[0m/g")
  
  # Fondo rojo para "Conversion failed!"
  line=$(echo "$line" | sed -E "s/(Conversion failed!)/\\x1b[41;97m\\1\\x1b[0m/g")

  # Fondo azul para "Streams activos ahora: ..."
  line=$(echo "$line" | sed -E "s/(Streams activos ahora: \[[^]]*\])/\\x1b[44;97m\\1\\x1b[0m/g")

  echo -e "$line"
done
exec bash'

