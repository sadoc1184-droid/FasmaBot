"""Statistica minima per il test dell'ipotesi nulla, senza dipendenze esterne.

Il banco di prova ha bisogno solo di: distribuzione ipergeometrica esatta,
chi-quadro di bonta' di adattamento e p-value. Implementarli qui evita di
trascinare scipy in un progetto che altrimenti dipende solo da pyswisseph.
"""

from __future__ import annotations

import math

TABELLONE = 90
ESTRATTI = 6
GIOCATI = 6


def log_binomial(n: int, k: int) -> float:
    if k < 0 or k > n:
        return float("-inf")
    return math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)


def hypergeometric_pmf(
    hits: int, population: int = TABELLONE, drawn: int = ESTRATTI, played: int = GIOCATI
) -> float:
    """P(esattamente `hits` numeri indovinati) su una giocata singola."""
    if hits < 0 or hits > min(drawn, played):
        return 0.0
    log_p = (
        log_binomial(drawn, hits)
        + log_binomial(population - drawn, played - hits)
        - log_binomial(population, played)
    )
    return math.exp(log_p)


def hypergeometric_distribution(
    population: int = TABELLONE, drawn: int = ESTRATTI, played: int = GIOCATI
) -> list[float]:
    """Distribuzione completa dei centri, da 0 a 6 indovinati."""
    return [hypergeometric_pmf(h, population, drawn, played) for h in range(played + 1)]


def expected_hits(
    population: int = TABELLONE, drawn: int = ESTRATTI, played: int = GIOCATI
) -> float:
    """Media dei numeri indovinati per giocata: played * drawn / population."""
    return played * drawn / population


def hits_variance(
    population: int = TABELLONE, drawn: int = ESTRATTI, played: int = GIOCATI
) -> float:
    """Varianza ipergeometrica dei numeri indovinati per giocata."""
    p = drawn / population
    return played * p * (1 - p) * (population - played) / (population - 1)


def normal_sf(z: float) -> float:
    """Coda superiore della normale standard."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def two_sided_p(z: float) -> float:
    return min(1.0, 2.0 * normal_sf(abs(z)))


def chi_square_gof(observed: list[int], expected: list[float]) -> tuple[float, int]:
    """Chi-quadro di bonta' di adattamento.

    Le classi con attesa inferiore a 5 vengono accorpate nell'ultima classe
    valida, come richiede l'approssimazione chi-quadro.
    """
    obs_pooled: list[float] = []
    exp_pooled: list[float] = []
    obs_acc = 0.0
    exp_acc = 0.0

    for obs, exp in zip(observed, expected):
        obs_acc += obs
        exp_acc += exp
        if exp_acc >= 5.0:
            obs_pooled.append(obs_acc)
            exp_pooled.append(exp_acc)
            obs_acc = exp_acc = 0.0

    if exp_acc > 0:
        if exp_pooled:
            obs_pooled[-1] += obs_acc
            exp_pooled[-1] += exp_acc
        else:
            obs_pooled.append(obs_acc)
            exp_pooled.append(exp_acc)

    stat = sum((o - e) ** 2 / e for o, e in zip(obs_pooled, exp_pooled) if e > 0)
    return stat, max(len(exp_pooled) - 1, 1)


def chi_square_sf(stat: float, df: int) -> float:
    """Coda superiore del chi-quadro via approssimazione di Wilson-Hilferty."""
    if stat <= 0:
        return 1.0
    ratio = stat / df
    z = (ratio ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
    return normal_sf(z)
