#!/usr/bin/env bash
# Avvia FoxBot caricando le variabili da .env
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "❌ File .env non trovato. Copia .env.example in .env e compila i valori."
  exit 1
fi

set -a; source "$ENV_FILE"; set +a

exec "$DIR/venv/bin/python" "$DIR/bot.py"
