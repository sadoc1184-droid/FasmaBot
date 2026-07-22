"""Gestisce i marker di delegazione GLM → Claude e la chiamata al bridge."""

import re
import subprocess
import shlex
from pathlib import Path

ASK_CLAUDE = str(Path.home() / "bin" / "ask-claude")

# Marker supportati nel testo di GLM:
#   [ASK_CLAUDE: --image /path "domanda"]   → analisi (risposta testuale)
#   [DO: descrizione compito completa]       → esecuzione (scrive file, comandi)

MARKER_RE = re.compile(
    r'\[(ASK_CLAUDE|DO):\s*(.*?)\]',
    re.DOTALL
)


def _run_bridge(args: list[str], timeout: int = 180) -> str:
    try:
        result = subprocess.run(
            [ASK_CLAUDE] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        out = result.stdout.strip()
        err = result.stderr.strip()
        return out or err or "Nessun output dal bridge."
    except subprocess.TimeoutExpired:
        return "Timeout: il bridge ha impiegato troppo."
    except Exception as e:
        return f"Errore bridge: {e}"


def call_answer(args_str: str) -> str:
    """Chiama Claude in modalità risposta (analisi, immagini, domande)."""
    return _run_bridge(shlex.split(args_str))


def call_do(task: str) -> str:
    """Chiama Claude in modalità esecuzione (scrivere file, creare progetti, comandi)."""
    return _run_bridge(["--do", task], timeout=300)


def process_markers(glm_reply: str, on_thinking=None) -> tuple[str, bool]:
    """
    Cerca marker [ASK_CLAUDE: ...] o [DO: ...] nella risposta di GLM.
    Ritorna (risultato_bridge, found) dove found=True se un marker è stato trovato.
    on_thinking: callback opzionale chiamata prima di eseguire (per mostrare "sto elaborando...")
    """
    match = MARKER_RE.search(glm_reply)
    if not match:
        return "", False

    kind    = match.group(1)   # "ASK_CLAUDE" o "DO"
    payload = match.group(2).strip()

    if on_thinking:
        on_thinking(kind)

    if kind == "ASK_CLAUDE":
        result = call_answer(payload)
    else:  # DO
        result = call_do(payload)

    return result, True
