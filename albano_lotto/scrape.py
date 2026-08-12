"""Recupero dell'archivio storico delle estrazioni da superenalotto.it.

L'archivio pubblico e' navigabile per anno/mese. Ogni pagina mensile contiene
una riga per concorso con numero, data, sestina, Jolly e SuperStar.

Uso:
    python3 -m albano_lotto.scrape --da 1997 --a 2026 --out archivio.csv

Le pagine gia' scaricate vengono tenute in cache su disco, cosi' una seconda
esecuzione non ricarica il sito.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BASE_URL = "https://www.superenalotto.it/archivio-estrazioni"
USER_AGENT = "albano-lotto/0.1 (studio statistico; contatto via repository)"

# Il SuperEnalotto e' partito il 3 dicembre 1997.
FIRST_YEAR = 1997

MONTHS = [
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
]
MONTH_INDEX = {name: i + 1 for i, name in enumerate(MONTHS)}

_ROW_SPLIT = re.compile(r'<tr class="superenalotto-extraction-archive__details__table__row')
_LABEL = re.compile(
    r"Concorso\s*<strong>N[º°o]?\s*(\d+)</strong>\s*del\s*<strong>\s*"
    r"(\d{1,2})\s+(\w+)\s+(\d{4})\s*</strong>",
    re.IGNORECASE,
)
_COMBINATION = re.compile(r'__combination__text">\s*(\d{1,2})\s*<')
_JOLLY = re.compile(r'__jolly__text">\s*(\d{1,2})\s*<')
_SUPERSTAR = re.compile(r'__superstar__text">\s*(\d{1,2})\s*<')


@dataclass(frozen=True)
class ScrapedDraw:
    concorso: int
    year: int
    month: int
    day: int
    numbers: tuple[int, ...]
    jolly: int | None
    superstar: int | None

    def as_csv_row(self) -> str:
        cells = [
            f"{self.year:04d}-{self.month:02d}-{self.day:02d}",
            *[str(n) for n in self.numbers],
            "" if self.jolly is None else str(self.jolly),
            "" if self.superstar is None else str(self.superstar),
            str(self.concorso),
        ]
        return ",".join(cells)


class MonthUnavailable(Exception):
    """Il mese non e' stato scaricato: pagina assente o errore di rete."""


def fetch_month(
    year: int, month_name: str, cache_dir: Path, delay: float = 0.4, retries: int = 3
) -> str:
    """Scarica (o rilegge dalla cache) la pagina di un mese.

    Solo le pagine scaricate con successo finiscono in cache. Un errore di rete
    non viene mai memorizzato come "mese vuoto": altrimenti un timeout
    transitorio cancellerebbe in silenzio un mese di estrazioni dall'archivio, e
    nessuna esecuzione successiva potrebbe piu' accorgersene.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{year}-{month_name}.html"
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="replace")

    url = f"{BASE_URL}/{year}/{month_name}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
            cached.write_text(html, encoding="utf-8")
            time.sleep(delay)
            return html
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # Mese realmente assente dall'archivio: esito legittimo e stabile.
                cached.write_text("", encoding="utf-8")
                time.sleep(delay)
                return ""
            last_error = exc
        except Exception as exc:
            last_error = exc
        time.sleep(delay * (2 ** attempt))

    raise MonthUnavailable(f"{year}/{month_name}: {last_error}")


def parse_month(html: str) -> list[ScrapedDraw]:
    """Estrae le estrazioni da una pagina mensile."""
    draws: list[ScrapedDraw] = []
    for block in _ROW_SPLIT.split(html)[1:]:
        label = _LABEL.search(block)
        if not label:
            continue
        month_name = label.group(3).lower()
        if month_name not in MONTH_INDEX:
            continue

        numbers = [int(n) for n in _COMBINATION.findall(block)]
        if len(numbers) != 6 or len(set(numbers)) != 6:
            continue

        jolly = _JOLLY.search(block)
        superstar = _SUPERSTAR.search(block)
        draws.append(
            ScrapedDraw(
                concorso=int(label.group(1)),
                year=int(label.group(4)),
                month=MONTH_INDEX[month_name],
                day=int(label.group(2)),
                numbers=tuple(numbers),
                jolly=int(jolly.group(1)) if jolly else None,
                superstar=int(superstar.group(1)) if superstar else None,
            )
        )
    return draws


def scrape(
    first_year: int, last_year: int, cache_dir: Path, delay: float = 0.4
) -> list[ScrapedDraw]:
    """Scorre tutti i mesi nell'intervallo e raccoglie le estrazioni."""
    collected: dict[tuple[int, int, int, int], ScrapedDraw] = {}
    failed: list[str] = []

    for year in range(first_year, last_year + 1):
        found = 0
        for month_name in MONTHS:
            try:
                html = fetch_month(year, month_name, cache_dir, delay=delay)
            except MonthUnavailable as exc:
                print(f"  ! {exc}", file=sys.stderr)
                failed.append(f"{year}/{month_name}")
                continue
            for draw in parse_month(html):
                # Il numero di concorso si azzera ogni anno: la chiave e' la data.
                collected[(draw.year, draw.month, draw.day, draw.concorso)] = draw
                found += 1
        print(f"  {year}: {found} estrazioni")

    if failed:
        # Meglio un errore rumoroso che un archivio con buchi silenziosi.
        raise MonthUnavailable(
            f"{len(failed)} mesi non scaricati: {', '.join(failed[:10])}"
            + (" ..." if len(failed) > 10 else "")
        )

    return sorted(collected.values(), key=lambda d: (d.year, d.month, d.day, d.concorso))


def write_csv(draws: list[ScrapedDraw], path: Path) -> None:
    lines = ["data,n1,n2,n3,n4,n5,n6,jolly,superstar,concorso"]
    lines += [d.as_csv_row() for d in draws]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--da", type=int, default=FIRST_YEAR, help="anno iniziale")
    parser.add_argument("--a", type=int, default=2026, help="anno finale")
    parser.add_argument("--out", default="archivio.csv", help="CSV di destinazione")
    parser.add_argument("--cache", default=".cache-archivio", help="cartella cache HTML")
    parser.add_argument("--delay", type=float, default=0.4, help="pausa tra richieste")
    args = parser.parse_args(argv)

    print(f"Scarico archivio {args.da}-{args.a} da superenalotto.it")
    draws = scrape(args.da, args.a, Path(args.cache), delay=args.delay)
    write_csv(draws, Path(args.out))
    print(f"\n{len(draws)} estrazioni salvate in {args.out}")
    if draws:
        first, last = draws[0], draws[-1]
        print(f"Prima: {first.year}-{first.month:02d}-{first.day:02d}")
        print(f"Ultima: {last.year}-{last.month:02d}-{last.day:02d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
