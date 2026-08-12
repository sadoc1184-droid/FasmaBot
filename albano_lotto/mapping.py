"""Mappatura longitudine eclittica -> numero del SuperEnalotto (1-90).

Lo zodiaco copre 360°, il tabellone del SuperEnalotto 90 numeri: ne segue una
corrispondenza esatta di 4° per numero, senza costanti arbitrarie.

    numero = floor(longitudine / 4) + 1

E' l'unico punto in cui il sistema converte un dato astronomico in un numero
giocabile: tenerlo isolato qui rende la scelta ispezionabile e sostituibile.
"""

from __future__ import annotations

DEGREES_PER_NUMBER = 4.0
LOTTO_MIN = 1
LOTTO_MAX = 90


def longitude_to_number(longitude: float) -> int:
    """Converte una longitudine eclittica nel numero 1-90 corrispondente."""
    return int((longitude % 360.0) // DEGREES_PER_NUMBER) + 1


def number_to_arc(number: int) -> tuple[float, float]:
    """Arco eclittico [inizio, fine) che genera un dato numero."""
    if not LOTTO_MIN <= number <= LOTTO_MAX:
        raise ValueError(f"numero fuori tabellone: {number}")
    start = (number - 1) * DEGREES_PER_NUMBER
    return start, start + DEGREES_PER_NUMBER


def resolve_collisions(numbers: list[int]) -> list[int]:
    """Rende univoca una sequenza di numeri preservando l'ordine gerarchico.

    Se due significatori cadono nello stesso arco di 4°, il secondo scorre in
    avanti sul tabellone fino al primo numero libero (con wrap 90 -> 1). Lo
    scorrimento e' deterministico: nessuna casualita' entra nel sistema.
    """
    seen: set[int] = set()
    resolved: list[int] = []
    for raw in numbers:
        candidate = raw
        while candidate in seen:
            candidate = candidate % LOTTO_MAX + 1
        seen.add(candidate)
        resolved.append(candidate)
    return resolved
