"""Punto di ingresso del package: `python3 -m albano_lotto` o `astrosoldi`.

Delega a `cli.py`, che resta lo strumento di sviluppo eseguibile dalla cartella
del progetto senza installare niente.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    # cli.py vive accanto al package, non dentro: quando si esegue il progetto
    # dai sorgenti la cartella e' gia' nel path, da package installato no.
    project_root = Path(__file__).resolve().parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    from cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
