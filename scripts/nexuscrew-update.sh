#!/usr/bin/env bash
# Aggiorna, riavvia e verifica NexusCrew su Scassone.
#
# Pensato per essere lanciato da un canale povero (bridge di FasmaBot, terminale
# del telefono): un comando solo, output leggibile, e alla fine dice se il
# servizio risponde davvero invece di limitarsi a "riavviato".
#
#   ./scripts/nexuscrew-update.sh            # aggiorna + riavvia + verifica
#   ./scripts/nexuscrew-update.sh --no-update  # solo riavvia + verifica
#
# Nota sudo: il pacchetto globale sta in /usr/lib/node_modules, quindi
# l'aggiornamento chiede la password. Se il canale non e' interattivo, usare
# --no-update per rimettere in piedi il servizio senza toccare l'installazione.

set -uo pipefail

UPDATE=1
[[ "${1:-}" == "--no-update" ]] && UPDATE=0

# I unit di NexusCrew sono --user: senza XDG_RUNTIME_DIR, systemctl non trova il
# bus quando il comando arriva da un contesto senza sessione (es. il servizio
# fasmagor, che gira come sadoc ma non ha una sessione utente).
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=${XDG_RUNTIME_DIR}/bus}"

step() { printf '\n=== %s ===\n' "$1"; }
ok()   { printf '  OK   %s\n' "$1"; }
ko()   { printf '  FAIL %s\n' "$1"; }

FAILED=0

step "Stato di partenza"
printf '  versione installata: %s\n' "$(nexuscrew version 2>/dev/null || echo 'non rilevata')"
printf '  linger utente: %s\n' \
  "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null || echo 'sconosciuto')"

# Linger spento = i unit --user non ripartono da soli dopo un reboot. E' la causa
# piu' comune di "NexusCrew non risponde piu'" senza che nulla sia rotto.
if [[ "$(loginctl show-user "$(id -un)" --property=Linger --value 2>/dev/null)" == "no" ]]; then
  printf '  ATTENZIONE: linger disattivato — dopo un riavvio il servizio non\n'
  printf '  riparte da solo. Sistemare con: sudo loginctl enable-linger %s\n' "$(id -un)"
fi

if [[ "$UPDATE" == "1" ]]; then
  step "Aggiornamento npm globale"
  if sudo npm install -g @mmmbuto/nexuscrew; then
    ok "installato: $(nexuscrew version 2>/dev/null || echo '?')"
  else
    ko "npm install fallito — il servizio resta sulla versione attuale"
    FAILED=1
  fi
fi

step "Riavvio del servizio"
if nexuscrew restart; then
  ok "nexuscrew restart"
elif systemctl --user restart nexuscrew; then
  ok "systemctl --user restart nexuscrew (fallback)"
else
  ko "riavvio fallito"
  FAILED=1
fi

step "Verifica"
if systemctl --user is-active --quiet nexuscrew; then
  ok "unit attiva"
else
  ko "unit non attiva — log: journalctl --user -u nexuscrew -n 50 --no-pager"
  FAILED=1
fi

# La porta non e' fissa: NexusCrew ne sceglie una libera e la scrive nel config.
PORT="$(python3 -c "
import json, pathlib
try:
    print(json.loads(pathlib.Path.home().joinpath('.nexuscrew/config.json').read_text()).get('port', ''))
except Exception:
    print('')
" 2>/dev/null)"

if [[ -n "$PORT" ]]; then
  CODE="$(curl -sS -o /dev/null -m 10 -w '%{http_code}' "http://127.0.0.1:${PORT}/" 2>/dev/null)"
  if [[ "$CODE" =~ ^(200|302|401)$ ]]; then
    ok "risponde su 127.0.0.1:${PORT} (http ${CODE})"
  else
    ko "nessuna risposta su 127.0.0.1:${PORT} (http ${CODE:-timeout})"
    FAILED=1
  fi
else
  ko "porta non leggibile da ~/.nexuscrew/config.json"
  FAILED=1
fi

# Il servizio ascolta solo su loopback: senza questa mappatura l'URL ts.net non
# porta da nessuna parte, anche con NexusCrew perfettamente vivo.
step "Ponte Tailscale"
if tailscale serve status 2>&1 | grep -q .; then
  tailscale serve status 2>&1 | sed 's/^/  /'
else
  ko "nessuna mappatura serve attiva — l'URL https://scassone... non risponde"
  printf '  rimetterla con: tailscale serve --bg http://127.0.0.1:%s\n' "${PORT:-PORTA}"
  FAILED=1
fi

step "Diagnostica"
nexuscrew doctor 2>&1 | sed 's/^/  /'

if [[ "$FAILED" == "0" ]]; then
  printf '\nTUTTO OK — https://scassone.tailb4894a.ts.net/ dovrebbe rispondere.\n'
else
  printf '\nCI SONO PROBLEMI — vedi le righe FAIL qui sopra.\n'
fi
exit "$FAILED"
