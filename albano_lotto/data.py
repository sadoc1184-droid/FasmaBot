"""Caricamento dell'archivio estrazioni e generazione di archivi sintetici.

L'archivio reale non e' incluso nel repository: va fornito come CSV. Il
formato atteso e' una riga per estrazione:

    data,n1,n2,n3,n4,n5,n6[,jolly[,superstar]]
    2026-08-11,7,13,28,44,61,89,12,5

La data puo' essere `YYYY-MM-DD` oppure `DD/MM/YYYY`. L'ora dell'estrazione,
se assente, e' fissata a 20:00 Europe/Rome (orario ufficiale del concorso).
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from .chart import ROME_TZ

DRAW_TIME = time(20, 0)

# Giorni di estrazione (0 = lunedi'). Configurabile: il calendario del concorso
# e' cambiato nel tempo, quindi non viene trattato come un fatto immutabile.
DEFAULT_DRAW_WEEKDAYS = (1, 3, 4, 5)


def is_draw_day(day: datetime, weekdays: tuple[int, ...] = DEFAULT_DRAW_WEEKDAYS) -> bool:
    """Vero se il giorno e' un giorno di estrazione ordinario.

    Attenzione: il calendario del concorso e' cambiato piu' volte e i festivi
    vengono posticipati caso per caso (es. Ferragosto). Questa funzione conosce
    solo la cadenza settimanale ordinaria: per le date spostate va confrontata
    con il calendario ufficiale.
    """
    return day.weekday() in weekdays


def next_draw_day(
    after: datetime, weekdays: tuple[int, ...] = DEFAULT_DRAW_WEEKDAYS
) -> datetime:
    """Prossimo giorno di estrazione ordinario a partire da `after` incluso.

    Se `after` e' gia' un giorno di estrazione ma l'ora dell'estrazione e' passata,
    restituisce il giorno utile successivo.
    """
    candidate = after
    if is_draw_day(candidate, weekdays) and (
        candidate.hour, candidate.minute
    ) < (DRAW_TIME.hour, DRAW_TIME.minute):
        return candidate.replace(
            hour=DRAW_TIME.hour, minute=DRAW_TIME.minute, second=0, microsecond=0
        )

    for _ in range(1, 15):
        candidate += timedelta(days=1)
        if is_draw_day(candidate, weekdays):
            return candidate.replace(
                hour=DRAW_TIME.hour, minute=DRAW_TIME.minute, second=0, microsecond=0
            )
    raise ValueError("nessun giorno di estrazione trovato nei prossimi 14 giorni")


@dataclass(frozen=True)
class Draw:
    """Una estrazione: momento ufficiale + numeri usciti."""

    moment: datetime
    numbers: tuple[int, ...]
    jolly: int | None = None
    superstar: int | None = None

    def __post_init__(self) -> None:
        if len(set(self.numbers)) != 6:
            raise ValueError(f"estrazione non valida (6 numeri distinti attesi): {self.numbers}")
        if not all(1 <= n <= 90 for n in self.numbers):
            raise ValueError(f"numeri fuori tabellone: {self.numbers}")


def _parse_date(raw: str) -> datetime:
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            parsed = datetime.strptime(raw, fmt)
            break
        except ValueError:
            continue
    else:
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"data non riconosciuta: {raw!r}") from exc

    if parsed.hour == 0 and parsed.minute == 0:
        parsed = parsed.replace(hour=DRAW_TIME.hour, minute=DRAW_TIME.minute)
    return parsed.replace(tzinfo=ROME_TZ)


def load_draws(path: str | Path) -> list[Draw]:
    """Legge un archivio CSV di estrazioni reali."""
    draws: list[Draw] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        for lineno, row in enumerate(reader, start=1):
            cells = [c.strip() for c in row if c.strip()]
            if not cells or cells[0].lower().startswith(("data", "date", "#")):
                continue
            if len(cells) < 7:
                raise ValueError(f"riga {lineno}: attese almeno 7 colonne, trovate {len(cells)}")
            draws.append(
                Draw(
                    moment=_parse_date(cells[0]),
                    numbers=tuple(int(c) for c in cells[1:7]),
                    jolly=int(cells[7]) if len(cells) > 7 else None,
                    superstar=int(cells[8]) if len(cells) > 8 else None,
                )
            )
    draws.sort(key=lambda d: d.moment)
    return draws


def simulate_draws(
    count: int,
    start: datetime | None = None,
    seed: int = 20260812,
    weekdays: tuple[int, ...] = DEFAULT_DRAW_WEEKDAYS,
) -> list[Draw]:
    """Genera un archivio sintetico con estrazioni uniformi indipendenti.

    Serve al test dell'ipotesi nulla: le estrazioni reali sono, per costruzione
    del concorso, indistinguibili da queste. Usare estrazioni simulate rende il
    banco di prova eseguibile senza dipendere da una fonte dati esterna.
    """
    rng = random.Random(seed)
    cursor = start or datetime(2015, 1, 1, DRAW_TIME.hour, DRAW_TIME.minute, tzinfo=ROME_TZ)
    draws: list[Draw] = []

    while len(draws) < count:
        if cursor.weekday() in weekdays:
            numbers = tuple(sorted(rng.sample(range(1, 91), 6)))
            remaining = [n for n in range(1, 91) if n not in numbers]
            draws.append(
                Draw(
                    moment=cursor,
                    numbers=numbers,
                    jolly=rng.choice(remaining),
                    superstar=rng.randint(1, 90),
                )
            )
        cursor += timedelta(days=1)
    return draws
