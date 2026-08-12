"""Astrosoldi — report della prossima estrazione SuperEnalotto per Telegram.

Sopra il motore vendorizzato in `albano_lotto/` (studio "albano-lotto" di
TarshishTradingSystem) c'e' solo la formattazione del messaggio e la regola di
consegna. La logica astrologica e statistica non viene toccata qui.

Regola del messaggio, come richiesto:
- verdetto ASTIENITI  → esce **solo** la parola ASTIENITI, nient'altro;
- verdetto GIOCA/INCERTO → escono le combinazioni da giocare.

Destinatari: solo Sadoc (`ASTRO_USER_IDS`, di default gli admin), non tutta
`ALLOWED_USER_IDS` come gli altri report del bot.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytz

log = logging.getLogger(__name__)

ROME_TZ = ZoneInfo("Europe/Rome")

# Lo stesso fuso, ma per il job queue: APScheduler <= 3.10 (quello che pinano le
# versioni 20.x di python-telegram-bot) rifiuta ZoneInfo con TypeError, mentre
# pytz va bene con qualunque versione. Stessa scelta di `ET_TZ` in stock.py.
ROME_TZ_SCHED = pytz.timezone("Europe/Rome")

# Quante combinazioni mettere nel messaggio quando il verdetto e' di giocare.
# Il motore ne sa produrre fino a `len(payload["ranked"])`: dieci sono il default
# della libreria, in chat cinque restano leggibili senza scrollare.
COMBINAZIONI = int(os.environ.get("ASTRO_COMBINAZIONI", "5"))

# Telegram non ha ne' colore ne' corpo del testo: bianco, grosso e grassetto si
# ottengono solo con il grassetto Markdown (che rende nel colore di default del
# tema, cioe' bianco su tema scuro) piu' le lettere spaziate, che allargano la
# parola sulla riga. E' il massimo risalto ottenibile in un messaggio di testo.
BANNER_ASTIENITI = "*A S T I E N I T I*"


def _astro_user_ids() -> set[int]:
    """Destinatari del report Astrosoldi.

    `ASTRO_USER_IDS` se valorizzata, altrimenti gli admin (Sadoc). Mai
    `ALLOWED_USER_IDS`: il report non deve arrivare agli utenti stock-only.
    """
    raw = os.environ.get("ASTRO_USER_IDS") or os.environ.get("ADMIN_USER_IDS", "")
    return {int(uid.strip()) for uid in raw.split(",") if uid.strip()}


def is_draw_day(momento: datetime | None = None) -> bool:
    """Vero nei giorni di estrazione ordinari (mar/gio/ven/sab).

    Attenzione, limite noto e dichiarato dallo studio: i posticipi per festivita'
    (es. Ferragosto) non sono gestiti — in quei giorni il report esce comunque e
    va letto per l'estrazione effettiva.
    """
    from albano_lotto.data import is_draw_day as _is_draw_day

    return _is_draw_day(momento or datetime.now(tz=ROME_TZ))


def build_astro_message(momento: datetime | None = None) -> str:
    """Messaggio Telegram (Markdown) per la prossima estrazione utile."""
    from albano_lotto.engine import ASTIENITI, INCERTO
    from albano_lotto.report import AVVERTENZA, NUMERO_VERDE, build_report, giorno_esteso

    report = build_report(momento=momento, quante=COMBINAZIONI)

    # Non si gioca: esce solo la parola, come richiesto. Nessuna combinazione,
    # nessuna avvertenza — non c'e' nessuna giocata proposta da avvertire.
    if report.verdetto == ASTIENITI:
        return BANNER_ASTIENITI

    righe = [
        f"🎰 *ASTROSOLDI* — estrazione di {giorno_esteso(report.momento)}, "
        f"ore {report.momento:%H:%M}",
    ]
    if report.verdetto == INCERTO:
        righe.append("Verdetto orario: *INCERTO* — testimonianze contraddittorie.")
    righe.append("")

    for c in report.combinazioni:
        righe.append("`" + "  ".join(f"{n:2d}" for n in c.numeri) + "`")

    righe += [
        "",
        f"Jolly *{report.jolly}* · SuperStar *{report.superstar}*",
        "",
        # L'avvertenza accompagna sempre una giocata proposta: vedi INTEGRAZIONE.md
        # dello studio, non e' decorazione e non va rimossa.
        f"_{AVVERTENZA}_",
        f"_Gioco d'azzardo problematico: numero verde {NUMERO_VERDE}._",
    ]
    return "\n".join(righe)


async def send_astro_report(bot, momento: datetime | None = None) -> None:
    """Genera il report e lo consegna ai soli destinatari Astrosoldi."""
    from telegram.constants import ParseMode

    try:
        text = build_astro_message(momento)
    except Exception as e:  # motore o effemeridi non disponibili: il bot resta vivo
        log.error("astro → build_astro_message fallito: %s", e)
        return

    for uid in _astro_user_ids():
        try:
            await bot.send_message(chat_id=uid, text=text, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            log.error("astro → %s fallito: %s", uid, e)
