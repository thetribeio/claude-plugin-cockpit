#!/bin/bash
# Mon Studio installé dans le HOME du bac à sable (jamais le vrai) : les hooks du plugin s'allument,
# comme chez un PM qui a fait /cockpit:mon-studio. Rien d'autre n'est posé.
set -e
mkdir -p "$HOME/Mon Studio/.parc"
printf '{"installedAt": "2026-11-01T08:00:00Z"}\n' > "$HOME/Mon Studio/.parc/cockpit.json"
