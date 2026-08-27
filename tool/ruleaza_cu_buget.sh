#!/usr/bin/env bash
# Rulează o unealtă de descărcare cu un buget de timp.
#
# De ce: sursele cresc, iar o reluare completă poate depăși fereastra rulării.
# Pe 26 aug 2026 prima probă a fost tăiată la limita de 330 de minute, blocată
# la „Cântările din cărți", fiindcă indexul de cântece adusese mii de intrări
# noi. Toate uneltele scriu cu flush la fiecare cântare, deci o oprire nu
# pierde nimic din ce s-a descărcat: restul se ia la rularea următoare.
#
# Bugetul depășit NU e o eroare, dar nici nu trece în tăcere: iese o notiță în
# rezumatul rulării, ca să se vadă că a rămas de lucru.
#
# Folosire: bash tool/ruleaza_cu_buget.sh 60m python3 tool/fetch_book_songs.py
set -uo pipefail

# `timeout` pe Linux (CI), `gtimeout` din coreutils pe Mac, ca proba să se
# poată face și local: o gardă pe care n-o poți exercita nu e o gardă.
TIMEOUT_BIN="$(command -v timeout || command -v gtimeout || true)"
if [ -z "$TIMEOUT_BIN" ]; then
  echo "Nu găsesc 'timeout' (pe Mac: brew install coreutils). Rulez fără buget." >&2
  shift
  exec "$@"
fi

buget="$1"
shift
"$TIMEOUT_BIN" "$buget" "$@"
rc=$?
if [ "$rc" -eq 124 ]; then
  echo "::notice title=Buget depășit::$* a atins bugetul de $buget. Ce a rămas se ia la rularea următoare."
  exit 0
fi
exit "$rc"
