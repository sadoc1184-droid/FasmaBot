"""Banco di prova a ipotesi nulla.

Questo modulo e' il motivo per cui il progetto vale la pena di esistere.

Il SuperEnalotto e' l'unico dominio in cui il valore vero del segnale e' noto
in anticipo ed e' esattamente zero. Passandoci dentro lo stesso impianto di
valutazione usato dai bot di trading del monorepo si ottiene una misura del
suo tasso di falsi positivi: se la procedura dichiara "edge" qui, allora ogni
edge che dichiara altrove va riesaminato.

Confronta tre strategie sullo stesso archivio:
  - `albano`   : numeri derivati dalla carta oraria dell'estrazione;
  - `random`   : numeri pseudocasuali (controllo attivo);
  - `fisso`    : sempre la stessa sestina (controllo degenere).
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from .data import Draw
from .engine import GIOCA, consult
from .stats import (
    chi_square_gof,
    chi_square_sf,
    expected_hits,
    hits_variance,
    hypergeometric_distribution,
    two_sided_p,
)

Strategy = Callable[[Draw], tuple[int, ...]]

FIXED_PICK = (1, 2, 3, 4, 5, 6)


def albano_strategy(draw: Draw) -> tuple[int, ...]:
    """Sestina prodotta dalla carta oraria eretta sul momento dell'estrazione."""
    return consult(draw.moment).numbers


def make_random_strategy(seed: int = 4242) -> Strategy:
    rng = random.Random(seed)

    def strategy(_: Draw) -> tuple[int, ...]:
        return tuple(sorted(rng.sample(range(1, 91), 6)))

    return strategy


def fixed_strategy(_: Draw) -> tuple[int, ...]:
    return FIXED_PICK


@dataclass(frozen=True)
class StrategyResult:
    """Esito di una strategia sull'intero archivio."""

    name: str
    draws: int
    hit_counts: tuple[int, ...]      # indice = numeri indovinati, valore = estrazioni
    total_hits: int

    @property
    def mean_hits(self) -> float:
        return self.total_hits / self.draws if self.draws else 0.0

    @property
    def z_score(self) -> float:
        """Scostamento della media osservata dall'attesa teorica, in sigma."""
        if not self.draws:
            return 0.0
        sigma = (hits_variance() / self.draws) ** 0.5
        return (self.mean_hits - expected_hits()) / sigma

    @property
    def p_value(self) -> float:
        return two_sided_p(self.z_score)

    def chi_square(self) -> tuple[float, int, float]:
        expected = [p * self.draws for p in hypergeometric_distribution()]
        stat, df = chi_square_gof(list(self.hit_counts), expected)
        return stat, df, chi_square_sf(stat, df)


def evaluate(
    draws: Sequence[Draw],
    strategy: Strategy,
    name: str,
    only_when_verdict: str | None = None,
) -> StrategyResult:
    """Applica una strategia a ogni estrazione e conta i numeri indovinati.

    Con `only_when_verdict` vengono considerate solo le estrazioni per cui il
    giudizio orario ha emesso quel verdetto: e' il test del filtro Albano.
    """
    counts = Counter()
    total = 0
    played = 0

    for draw in draws:
        if only_when_verdict is not None and consult(draw.moment).verdict != only_when_verdict:
            continue
        picked = set(strategy(draw))
        hits = len(picked & set(draw.numbers))
        counts[hits] += 1
        total += hits
        played += 1

    return StrategyResult(
        name=name,
        draws=played,
        hit_counts=tuple(counts.get(h, 0) for h in range(7)),
        total_hits=total,
    )


# Decorrelazione del controllo casuale rispetto all'archivio sintetico.
#
# Se il controllo e l'archivio partono dallo stesso seed, `random.Random` genera
# la stessa prima sestina in entrambi e il controllo "indovina" un 6 alla prima
# estrazione. E' successo davvero alla prima esecuzione del banco di prova, ed e'
# la ragione per cui questo scarto esiste: un controllo correlato ai dati non e'
# un controllo. Lo stesso identico errore, in un backtest di trading, si presenta
# come look-ahead bias.
CONTROL_SEED_OFFSET = 0xA5A5A5A5


def run_benchmark(draws: Sequence[Draw], seed: int = 4242) -> list[StrategyResult]:
    """Esegue le tre strategie di confronto piu' il filtro sul verdetto."""
    results = [
        evaluate(draws, albano_strategy, "albano"),
        evaluate(draws, make_random_strategy(seed ^ CONTROL_SEED_OFFSET), "random"),
        evaluate(draws, fixed_strategy, "fisso"),
        evaluate(draws, albano_strategy, "albano|solo GIOCA", only_when_verdict=GIOCA),
    ]
    return results


def format_report(results: Iterable[StrategyResult]) -> str:
    """Tabella comparativa + verdetto metodologico."""
    theoretical = hypergeometric_distribution()
    lines = [
        "BANCO DI PROVA A IPOTESI NULLA — SuperEnalotto",
        "=" * 78,
        "",
        f"Attesa teorica per sestina: {expected_hits():.4f} numeri indovinati.",
        "Distribuzione ipergeometrica dei centri (percentuale delle estrazioni):",
        "  " + "   ".join(f"{h}:{p * 100:7.4f}%" for h, p in enumerate(theoretical)),
        "",
        f"{'strategia':22s} {'estraz.':>8s} {'media':>8s} {'attesa':>8s} "
        f"{'z':>7s} {'p':>8s} {'chi2':>8s} {'p(chi2)':>8s}",
        "-" * 78,
    ]

    for r in results:
        stat, df, p_chi = r.chi_square()
        lines.append(
            f"{r.name:22s} {r.draws:8d} {r.mean_hits:8.4f} {expected_hits():8.4f} "
            f"{r.z_score:+7.2f} {r.p_value:8.4f} {stat:8.2f} {p_chi:8.4f}"
        )

    lines += ["", "Ripartizione dei centri osservati:", ""]
    lines.append(f"{'strategia':22s} " + " ".join(f"{h:>7d}" for h in range(7)))
    lines.append("-" * 78)
    for r in results:
        lines.append(f"{r.name:22s} " + " ".join(f"{c:>7d}" for c in r.hit_counts))

    significant = [r.name for r in results if r.p_value < 0.05]
    lines += ["", "VERDETTO METODOLOGICO", "-" * 78]
    if significant:
        lines.append(
            "Almeno una strategia devia dall'attesa con p < 0.05: "
            + ", ".join(significant) + "."
        )
        lines.append(
            "Poiche' il valore vero dell'edge e' zero per costruzione, questo e' "
            "un falso positivo. Se lo stesso impianto di valutazione produce "
            "questa deviazione qui, la stessa deviazione altrove non e' prova di edge."
        )
    else:
        lines.append(
            "Nessuna strategia devia dall'attesa teorica in modo significativo "
            "(p >= 0.05 su tutte). L'impianto di valutazione non ha prodotto "
            "falsi positivi su questo campione: si comporta correttamente sul nulla."
        )
    return "\n".join(lines)
